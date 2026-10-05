"""Skill dependency resolution via ``requires:`` DAG (stdlib topo sort).

Resolves ``requires: [skill_a, skill_b]`` frontmatter into a deterministic
dependency-first order, detects cycles, and fails on missing skills.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from typing import Any

from cinch.errors import CinchError

__all__ = [
    "parse_requires",
    "requires_from_meta",
    "resolve_skill_order",
    "expand_with_requires",
]


def parse_requires(raw: Any) -> tuple[str, ...]:
    """Normalize a raw ``requires`` frontmatter value to skill names.

    Accepts a string, list/tuple of strings, or ``None``/empty. Raises
    :class:`CinchError` on invalid types or empty names.
    """
    if raw is None or raw == "" or raw == []:
        return ()
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            raise CinchError("Invalid requires: skill name must be a non-empty string")
        return (name,)
    if isinstance(raw, (list, tuple)):
        names: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                raise CinchError(
                    f"Invalid requires: expected list of skill name strings, "
                    f"got {type(item).__name__}"
                )
            name = item.strip()
            if not name:
                raise CinchError("Invalid requires: skill name must be a non-empty string")
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        return tuple(names)
    raise CinchError(
        f"Invalid requires: expected string or list of strings, got {type(raw).__name__}"
    )


def requires_from_meta(meta: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Extract ``requires`` from frontmatter meta (empty if absent)."""
    if not meta or "requires" not in meta:
        return ()
    return parse_requires(meta.get("requires"))


def resolve_skill_order(
    roots: Iterable[str],
    graph: Mapping[str, Iterable[str]],
    *,
    available: Iterable[str] | None = None,
) -> list[str]:
    """Topologically sort ``roots`` and their transitive ``requires`` deps.

    ``graph`` maps skill name → direct dependency names (from ``requires``).
    Skills with no entry are treated as having no dependencies.

    Returns dependency-first order (prerequisites before dependents). Shared
    prerequisites appear once. Raises :class:`CinchError` on missing skills
    or cycles.

    When ``available`` is provided, every referenced skill (roots and deps)
    must appear in that set; otherwise only keys reachable through ``graph``
    plus roots that have no deps are accepted (missing deps still error).
    """
    root_list = list(dict.fromkeys(n.strip() for n in roots if n and str(n).strip()))
    if not root_list:
        return []

    avail: set[str] | None = None
    if available is not None:
        avail = {n for n in available}

    # Collect closure and validate missing deps against the catalog when given.
    closure: set[str] = set()
    stack = list(root_list)
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        if avail is not None and name not in avail:
            raise CinchError(f"Unknown required skill '{name}'")
        closure.add(name)
        for dep in graph.get(name, ()):
            if not isinstance(dep, str):
                continue
            dep = dep.strip()
            if not dep:
                continue
            if avail is not None and dep not in avail:
                raise CinchError(f"Unknown required skill '{dep}' (required by '{name}')")
            if dep not in closure:
                stack.append(dep)

    # Build adjacency (edge: dep → dependent) and indegree for Kahn.
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {n: 0 for n in closure}

    for name in closure:
        for dep in graph.get(name, ()):
            if not isinstance(dep, str):
                continue
            dep = dep.strip()
            if not dep or dep not in closure:
                continue
            # name requires dep → edge dep → name
            dependents[dep].append(name)
            indegree[name] = indegree.get(name, 0) + 1

    # Prefer requires declaration order (DFS post-order from roots), then name.
    pref = _declaration_preference(root_list, graph, closure)

    def _ready_key(n: str) -> tuple[int, str]:
        return (pref.get(n, len(pref)), n)

    ready = deque(sorted((n for n, d in indegree.items() if d == 0), key=_ready_key))
    order: list[str] = []
    while ready:
        node = ready.popleft()
        order.append(node)
        newly_ready: list[str] = []
        for nxt in dependents.get(node, ()):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                newly_ready.append(nxt)
        if newly_ready:
            ready.extend(newly_ready)
            ready = deque(sorted(ready, key=_ready_key))

    if len(order) != len(closure):
        remaining = sorted(closure - set(order))
        cycle = _find_cycle(remaining, graph)
        path = " -> ".join(cycle) if cycle else " -> ".join(remaining)
        raise CinchError(f"Circular skill dependency detected: {path}")

    return order


def _declaration_preference(
    roots: list[str],
    graph: Mapping[str, Iterable[str]],
    closure: set[str],
) -> dict[str, int]:
    """DFS post-order ranks so listed requires precede their dependents."""
    ranks: dict[str, int] = {}
    counter = 0

    def dfs(name: str) -> None:
        nonlocal counter
        if name in ranks or name not in closure:
            return
        # Sentinel so diamond deps don't re-enter before rank is assigned.
        ranks[name] = -1
        for dep in graph.get(name, ()):
            if not isinstance(dep, str):
                continue
            dep = dep.strip()
            if dep and dep in closure:
                dfs(dep)
        ranks[name] = counter
        counter += 1

    for root in roots:
        dfs(root)
    # Any leftover closure nodes (shouldn't happen) sort after.
    for name in sorted(closure):
        if name not in ranks or ranks[name] < 0:
            ranks[name] = counter
            counter += 1
    return ranks


def expand_with_requires(
    selected: Iterable[str],
    graph: Mapping[str, Iterable[str]],
    *,
    available: Iterable[str] | None = None,
) -> list[str]:
    """Expand selected skill names with transitive requires (topo-sorted)."""
    return resolve_skill_order(selected, graph, available=available)


def _find_cycle(nodes: Iterable[str], graph: Mapping[str, Iterable[str]]) -> list[str] | None:
    """Return one cycle path among ``nodes``, or None if not found."""
    node_set = set(nodes)
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in visited:
            return None
        if node in visiting:
            if node in path:
                idx = path.index(node)
                return path[idx:] + [node]
            return [node, node]
        visiting.add(node)
        path.append(node)
        for dep in graph.get(node, ()):
            if not isinstance(dep, str):
                continue
            dep = dep.strip()
            if dep not in node_set:
                continue
            found = dfs(dep)
            if found is not None:
                return found
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for start in sorted(node_set):
        found = dfs(start)
        if found is not None:
            return found
    return None
