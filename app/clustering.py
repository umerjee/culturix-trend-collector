import math
import random
from typing import List, Tuple


def euclidean_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def vector_mean(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    length = len(vectors[0])
    mean = [0.0] * length
    for vector in vectors:
        for i, value in enumerate(vector):
            mean[i] += value
    count = len(vectors)
    return [value / count for value in mean]


def assign_clusters(vectors: List[List[float]], centroids: List[List[float]]) -> List[int]:
    labels = []
    for vector in vectors:
        best_index = 0
        best_distance = float("inf")
        for index, centroid in enumerate(centroids):
            distance = euclidean_distance(vector, centroid)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        labels.append(best_index)
    return labels


def cluster_embeddings(embeddings: List[List[float]], num_clusters: int = 3, max_iters: int = 100) -> List[int]:
    if not embeddings or num_clusters <= 0:
        return []

    if num_clusters >= len(embeddings):
        return list(range(len(embeddings)))

    centroids = random.sample(embeddings, num_clusters)
    labels: List[int] = []

    for _ in range(max_iters):
        new_labels = assign_clusters(embeddings, centroids)
        if new_labels == labels:
            break
        labels = new_labels

        clusters = {i: [] for i in range(num_clusters)}
        for vector, label in zip(embeddings, labels):
            clusters[label].append(vector)

        new_centroids = []
        for i in range(num_clusters):
            cluster_vectors = clusters[i]
            if cluster_vectors:
                new_centroids.append(vector_mean(cluster_vectors))
            else:
                new_centroids.append(centroids[i])

        shift = sum(euclidean_distance(old, new) for old, new in zip(centroids, new_centroids))
        centroids = new_centroids
        if shift < 1e-4:
            break

    return labels
