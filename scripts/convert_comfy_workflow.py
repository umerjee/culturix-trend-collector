"""Converts a ComfyUI **UI-format** workflow (nodes + links + subgraph
definitions, i.e. what the official template library ships) into the
flat **API-format** dict our worker submits to ComfyUI's /prompt:

    {node_id: {"class_type": ..., "inputs": {...}}}

Why this exists: the UI format stores widget values *positionally*
(`widgets_values: [...]`) with no input names attached. Recovering the
names requires each node class's real input schema, which only a running
ComfyUI can supply via GET /object_info. Hand-guessing that mapping is
precisely how the LTX-2.3 workflow ended up silently missing its
`LTXVConditioning` node — the model then got no frame-rate signal and
produced near-static output. So this script refuses to guess: point it at
a ComfyUI that actually has the target nodes installed.

The RunPod worker already runs ComfyUI on 127.0.0.1:8188, so this can be
run there (or against any local ComfyUI with the LTX-2.5 nodes) without
extra infrastructure.

Usage:
    python scripts/convert_comfy_workflow.py \
        --input app/media/workflows/ltx25_official/video_ltx2_5_i2v.json \
        --output app/media/workflows/ltx25_image_to_video.api.json \
        --comfyui http://127.0.0.1:8188
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _fetch_object_info(base_url: str) -> dict:
    import httpx

    resp = httpx.get(f"{base_url.rstrip('/')}/object_info", timeout=60)
    resp.raise_for_status()
    return resp.json()


_PRIMITIVE_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}


def _ordered_input_names(class_schema: dict) -> list:
    """Widget values appear in the order ComfyUI declares required-then-
    optional inputs, skipping link-only (node-connection) inputs. Only
    inputs that occupy a widget slot are returned.

    A widget input is either a combo — expressed EITHER as a list of
    choices, or as the literal string "COMBO" when the choices are supplied
    dynamically (e.g. LatentUpscaleModelLoader.model_name) — or a primitive.
    Missing the string form silently dropped such inputs entirely, leaving
    e.g. VAELoader/LatentUpscaleModelLoader with no filename at all.

    Ordering comes from the schema's own `input_order`, NOT from iterating
    the `input` dict: /object_info serialises that dict ALPHABETICALLY, so
    iterating it silently scrambles the positional mapping. Confirmed
    against EmptyLTXVLatentVideo, whose widgets are [768, 512, 97, 1]
    (width, height, length, batch_size) while the dict iterates as
    batch_size, height, length, width — mapping width's 768 onto
    batch_size. `input_order` gives the real declaration order.
    """
    names = []
    spec = class_schema.get("input", {}) or {}
    order = class_schema.get("input_order") or {}
    for section in ("required", "optional"):
        section_spec = spec.get(section) or {}
        # Fall back to dict order only if input_order is absent (older
        # ComfyUI); it is the best available signal then, not a correct one.
        ordered_names = order.get(section) or list(section_spec.keys())
        for name in ordered_names:
            definition = section_spec.get(name)
            if not isinstance(definition, (list, tuple)) or not definition:
                continue
            type_spec = definition[0]
            is_combo = isinstance(type_spec, list) or type_spec == "COMBO"
            # Types can be a UNION expressed as a comma-separated string —
            # LTXVEmptyLatentAudio.frame_rate is "FLOAT,INT". An exact-match
            # check drops those, which shifts every later widget by one
            # position (it put frame_rate's 25 into batch_size).
            is_primitive = isinstance(type_spec, str) and any(
                part.strip() in _PRIMITIVE_TYPES for part in type_spec.split(",")
            )
            if is_combo or is_primitive:
                names.append(name)
    return names


def _collect_nodes(workflow: dict) -> tuple:
    """Returns (nodes, links). Flattens a single top-level subgraph when the
    template wraps its real graph in one (the LTX-2.5 templates do)."""
    nodes = list(workflow.get("nodes") or [])
    links = list(workflow.get("links") or [])
    subgraphs = ((workflow.get("definitions") or {}).get("subgraphs")) or []
    for sub in subgraphs:
        nodes.extend(sub.get("nodes") or [])
        links.extend(sub.get("links") or [])
    return nodes, links


def convert(workflow: dict, object_info: dict) -> dict:
    nodes, links = _collect_nodes(workflow)

    # link id -> (origin_node_id, origin_slot). UI links are
    # [link_id, origin_node, origin_slot, target_node, target_slot, type].
    link_sources: dict[Any, list] = {}
    for link in links:
        if isinstance(link, dict):
            link_sources[link.get("id")] = [str(link.get("origin_id")), link.get("origin_slot", 0)]
        elif isinstance(link, (list, tuple)) and len(link) >= 3:
            link_sources[link[0]] = [str(link[1]), link[2]]

    api: dict[str, dict] = {}
    skipped: list[str] = []
    for node in nodes:
        class_type = node.get("type")
        node_id = str(node.get("id"))
        # Notes/previews carry no execution semantics.
        if not class_type or class_type in {"MarkdownNote", "Note", "PreviewAny", "Reroute"}:
            continue
        schema = object_info.get(class_type)
        if not schema:
            skipped.append(class_type)
            continue

        inputs: dict[str, Any] = {}

        # 1) linked inputs, by declared name on the node itself
        for slot in node.get("inputs") or []:
            name, link_id = slot.get("name"), slot.get("link")
            if name and link_id is not None and link_id in link_sources:
                inputs[name] = link_sources[link_id]

        # 2) widget values, positionally against the schema's widget inputs.
        #
        # A widget input that is ALSO linked still occupies its slot in
        # widgets_values (ComfyUI keeps the last widget value there, and the
        # node's own `inputs` entry carries both `widget` and a non-null
        # `link`). So the positional walk must cover EVERY widget name and
        # skip the linked ones in place — compacting the name list first
        # shifts every later value by one, which silently put the
        # transformer filename into UNETLoader.weight_dtype instead of
        # unet_name.
        widget_values = node.get("widgets_values")
        if isinstance(widget_values, dict):
            for name, value in widget_values.items():
                if name not in inputs:
                    inputs[name] = value
        elif isinstance(widget_values, list):
            for name, value in zip(_ordered_input_names(schema), widget_values):
                if name in inputs:
                    continue  # satisfied by a link; its slot is still consumed
                inputs[name] = value

        api[node_id] = {"class_type": class_type, "inputs": inputs}

    if skipped:
        unique = sorted(set(skipped))
        print(
            f"WARNING: {len(unique)} node class(es) missing from this ComfyUI's /object_info "
            f"and therefore DROPPED: {unique}\n"
            "         The target ComfyUI must have the LTX-2.5 nodes installed, or the "
            "converted graph will be silently incomplete.",
            file=sys.stderr,
        )
    return api


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="UI-format workflow JSON")
    parser.add_argument("--output", required=True, help="where to write API-format JSON")
    parser.add_argument("--comfyui", default="http://127.0.0.1:8188", help="running ComfyUI base URL")
    parser.add_argument("--object-info", help="path to a saved /object_info JSON, instead of fetching")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    if args.object_info:
        with open(args.object_info, "r", encoding="utf-8") as f:
            object_info = json.load(f)
    else:
        object_info = _fetch_object_info(args.comfyui)

    api = convert(workflow, object_info)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(api, f, indent=2)

    classes = sorted({n["class_type"] for n in api.values()})
    print(f"Wrote {args.output}: {len(api)} nodes, {len(classes)} distinct classes")
    for c in classes:
        print(f"  - {c}")


if __name__ == "__main__":
    main()
