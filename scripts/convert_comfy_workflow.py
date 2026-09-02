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


_BOUNDARY_ORIGIN = -10  # ComfyUI's marker for "comes from the subgraph's own input"
_BOUNDARY_OUTPUT = -20  # ...and for "goes to the subgraph's own output"


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


def _boundary_values(workflow: dict) -> dict:
    """Resolves each subgraph input slot to a concrete value or upstream link.

    The LTX-2.5 templates put the real graph inside a subgraph and drive it
    from a wrapper node in the outer graph. Inside the subgraph, links from
    the boundary carry `origin_id: -10` and an `origin_slot` indexing the
    subgraph's declared `inputs` (first_frame, prompt, duration, width,
    height, ...). Without resolving these, every driveable input — the
    prompt and the reference image included — is a dangling reference to a
    node that doesn't exist in the flattened output.

    Each wrapper input either carries a `link` (wired in the outer graph,
    e.g. first_frame <- LoadImage) or a `widget` (a literal in the wrapper's
    own widgets_values). Widget entries consume widgets_values positionally,
    so only they advance that counter.

    Returns {slot_index: ("link", [node_id, slot]) | ("value", literal)}.
    """
    subgraphs = ((workflow.get("definitions") or {}).get("subgraphs")) or []
    if not subgraphs:
        return {}
    subgraph_ids = {s.get("id") for s in subgraphs}

    outer_links = {}
    for link in workflow.get("links") or []:
        if isinstance(link, dict):
            outer_links[link.get("id")] = [str(link.get("origin_id")), link.get("origin_slot", 0)]
        elif isinstance(link, (list, tuple)) and len(link) >= 3:
            outer_links[link[0]] = [str(link[1]), link[2]]

    by_id = {s.get("id"): s for s in subgraphs}

    resolved = {}
    for node in workflow.get("nodes") or []:
        sub = by_id.get(node.get("type"))
        if sub is None:
            continue
        widget_values = node.get("widgets_values") or []
        # Index by the SUBGRAPH's declared inputs, not the wrapper node's
        # own `inputs` array. Links inside the subgraph use origin_slot to
        # index the former, and the two differ: the i2v template declares
        # 14 subgraph inputs but the wrapper lists only 11 (widget-only
        # ones like noise_seed/unet_name/clip_name have no wrapper entry).
        # Walking the wrapper shifted every model filename by several slots
        # — ComfyUI rejected the graph with the transformer filename in
        # vae_name and a seed integer in unet_name.
        wrapper_links = {}
        for slot in node.get("inputs") or []:
            label = slot.get("label") or slot.get("name")
            if label and slot.get("link") is not None:
                wrapper_links[label] = slot["link"]

        widget_i = 0
        for slot_i, decl in enumerate(sub.get("inputs") or []):
            label = decl.get("label") or decl.get("name")
            type_spec = decl.get("type") or ""
            is_widget = type_spec == "COMBO" or any(
                part.strip() in _PRIMITIVE_TYPES for part in str(type_spec).split(",")
            )
            link_id = wrapper_links.get(label)
            if link_id is not None and link_id in outer_links:
                # Explicitly wired in the outer graph (e.g. width/height from
                # ResolutionSelector) — the link wins over the stale widget
                # value, but the widget slot is still consumed.
                resolved[slot_i] = ("link", outer_links[link_id])
            elif is_widget and widget_i < len(widget_values):
                resolved[slot_i] = ("value", widget_values[widget_i])
            if is_widget:
                widget_i += 1
    return resolved


def _boundary_outputs(workflow: dict) -> dict:
    """Maps each subgraph OUTPUT slot to the internal node that produces it.

    Inside the subgraph, a link to the boundary carries `target_id: -20`
    and a `target_slot` indexing the subgraph's declared `outputs`. The
    outer graph consumes those via the wrapper node (e.g. SaveVideo <-
    subgraph VIDEO). Since the wrapper itself is dropped when flattening,
    those consumers must be redirected to the real producer or they dangle.

    Returns {output_slot: [node_id, slot]}.
    """
    resolved = {}
    for sub in ((workflow.get("definitions") or {}).get("subgraphs")) or []:
        for link in sub.get("links") or []:
            if not isinstance(link, dict):
                continue
            if link.get("target_id") == _BOUNDARY_OUTPUT:
                resolved[link.get("target_slot", 0)] = [
                    str(link.get("origin_id")), link.get("origin_slot", 0)
                ]
    return resolved


def convert(workflow: dict, object_info: dict) -> dict:
    nodes, links = _collect_nodes(workflow)

    # link id -> (origin_node_id, origin_slot). UI links are
    # [link_id, origin_node, origin_slot, target_node, target_slot, type].
    boundary = _boundary_values(workflow)
    boundary_outputs = _boundary_outputs(workflow)
    subgraph_instance_ids = {
        str(n.get('id')) for n in (workflow.get('nodes') or [])
        if n.get('type') in {s.get('id') for s in ((workflow.get('definitions') or {}).get('subgraphs')) or []}
    }

    # link id -> ("link", [origin_node_id, origin_slot]) | ("value", literal)
    link_sources: dict[Any, tuple] = {}
    for link in links:
        if isinstance(link, dict):
            lid, origin, slot = link.get("id"), link.get("origin_id"), link.get("origin_slot", 0)
        elif isinstance(link, (list, tuple)) and len(link) >= 3:
            lid, origin, slot = link[0], link[1], link[2]
        else:
            continue
        if str(origin) in subgraph_instance_ids:
            # An outer-graph node consuming the SUBGRAPH's output (e.g.
            # SaveVideo <- the subgraph's VIDEO). Redirect it to the
            # internal node that actually produces that output, otherwise
            # it dangles at the dropped wrapper node.
            if slot in boundary_outputs:
                link_sources[lid] = ("link", boundary_outputs[slot])
            continue
        if origin == _BOUNDARY_ORIGIN:
            # Comes from the subgraph's own input — substitute whatever the
            # wrapper node supplies for that slot, else drop it so the
            # dangling reference doesn't reach the graph.
            if slot in boundary:
                link_sources[lid] = boundary[slot]
            continue
        link_sources[lid] = ("link", [str(origin), slot])

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
                kind, payload = link_sources[link_id]
                # A boundary-resolved literal becomes a plain input value;
                # a real link stays a [node_id, slot] reference.
                inputs[name] = payload

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
