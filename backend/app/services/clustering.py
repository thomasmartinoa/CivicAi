"""Group complaints that describe the same problem in the same place.

v1 bucketed on `f"{category}|{round(lat, 2)}|{round(lng, 2)}"`: two reports of
one collapsed road grouped only if the classifier happened to give them the
same label *and* their coordinates rounded into the same ~1 km cell. Two
complaints 200 m apart either shared a cell or straddled an edge, and nothing
about the wording mattered.

Here distance is continuous (haversine, a radius in kilometres) and matching is
on meaning (cosine over the same 768-dimensional embeddings the RAG stack
uses). The category is deliberately *not* part of the match — "the contractor
dug up MG Road" and "the MG Road surface caved in" are one job for one crew
however they were classified — but the cluster inherits its lead's category, so
the grouped work order still has exactly one department to route to.

This module is the pure half: lists in, clusters out, no database and no model.
The hourly job that reads complaints and writes work orders is built on top of
it.
"""

from dataclasses import dataclass
from datetime import datetime
from math import asin, cos, radians, sin, sqrt

import numpy as np

from app.ai.rag.embeddings import Embedder

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Candidate:
    """One complaint, reduced to what clustering needs.

    A plain dataclass rather than the ORM object so the algorithm can be tested
    without a database, and so nothing here can lazily load a relationship.
    """

    id: str
    text: str
    coords: tuple[float, float]
    priority: int
    created_at: datetime
    category: str


@dataclass
class Cluster:
    lead: Candidate
    members: list[Candidate]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def ids(self) -> list[str]:
        return [m.id for m in self.members]

    @property
    def category(self) -> str:
        """The lead's category: a cluster may span categories, but a work order
        routes to one department."""
        return self.lead.category


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres.

    Not Euclidean on raw degrees: a degree of longitude is ~111 km at the
    equator and ~0 at the poles, so a plain subtraction would make the radius
    mean different things in different cities.
    """
    lat1, lon1 = radians(a[0]), radians(a[1])
    lat2, lon2 = radians(b[0]), radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, h)))


def cosine(u: np.ndarray, v: np.ndarray) -> float:
    """Cosine similarity. Normalises even though the embedders return unit
    vectors — a future embedder that does not would otherwise skew every
    comparison silently."""
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0 or nv == 0:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


def cluster_candidates(
    candidates: list[Candidate],
    *,
    embedder: Embedder,
    radius_km: float,
    threshold: float,
    min_size: int,
) -> list[Cluster]:
    """Group candidates by similarity within a radius. Greedy, deterministic.

    The walk is ordered by descending priority, then oldest first, then id, so
    the most urgent report leads its cluster and the same input always produces
    the same output whatever order it arrives in.

    A lead claims every unclaimed candidate that is both within `radius_km` and
    at or above `threshold` cosine. If the group does not reach `min_size` the
    claims are released, so those candidates remain available to a later lead —
    a pair is not a cluster, but it must not be consumed as one either.
    """
    if len(candidates) < max(2, min_size):
        # Nothing can group, so do not pay for embeddings at all. The hourly
        # job runs against a real embedding API.
        return []

    ordered = sorted(candidates, key=lambda c: (-c.priority, c.created_at, c.id))
    vectors = np.asarray(embedder.embed_documents([c.text for c in ordered]), dtype="float32")

    claimed: set[str] = set()
    clusters: list[Cluster] = []

    for i, lead in enumerate(ordered):
        if lead.id in claimed:
            continue
        members = [lead]
        for j, other in enumerate(ordered):
            if i == j or other.id in claimed:
                continue
            if haversine_km(lead.coords, other.coords) > radius_km:
                continue
            if cosine(vectors[i], vectors[j]) < threshold:
                continue
            members.append(other)
        if len(members) < min_size:
            continue  # nothing claimed yet, so the members stay available
        claimed.update(m.id for m in members)
        clusters.append(Cluster(lead=lead, members=members))

    return clusters
