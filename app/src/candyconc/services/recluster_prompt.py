from __future__ import annotations

from typing import Any, Dict, List

SYSTEM_PROMPT = (
    "You are a corpus-linguistics assistant.\n"
    "You get pre-clustered concordance groups with IDs, current labels and two sample lines.\n"
    "Your task: suggest JSON instructions to merge truly identical topics, split obviously mixed clusters, and rename labels if they clash or are vague.\n"
    "Rules:\n"
    "- Use only IDs given.\n"
    "- Max 6 merges, 3 splits.\n"
    "- New label \u22643 words, no duplicates.\n"
    "Return **only** valid JSON matching this schema:\n"
    "{merges:[[id,id],\u2026], splits:[{id:int, subsets:[[int,\u2026],[int,\u2026]]}], renames:{id:str,\u2026}}"
)


def build_prompt(clusters: List[Dict[str, Any]], sim_candidates: Dict[int, List[int]]) -> str:
    """Return compact user prompt for reclustering."""
    lines: list[str] = []
    for cl in clusters:
        cid_raw = cl.get("id")
        if cid_raw is None:
            continue
        cid: int = int(cid_raw)
        label = cl.get("label", "")
        size = cl.get("size", 0)
        samples: list[str] = cl.get("samples") or cl.get("examples") or []
        lines.append(f"Cluster {cid} – label: \"{label}\" (size {size})")
        for i, s in enumerate(samples[:2]):
            lines.append(f"   {chr(97 + i)}) {s}")
        sims: list[int] = sim_candidates.get(cid, [])[:3]
        if sims:
            lines.append("Similar to: " + ", ".join(str(s) for s in sims))
        lines.append("")
    return "\n".join(lines).strip()
