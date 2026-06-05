import numpy as np
import hdbscan

def cluster_embeddings_hdbscan(embeddings, min_cluster_size=5):
    X = np.array(embeddings)

    clusterer = hdbscan.HDBSCAN(
    min_cluster_size=min_cluster_size,
    metric="euclidean",
    cluster_selection_method="leaf"   # ← switched from "eom"
)


    labels = clusterer.fit_predict(X)

    return labels
