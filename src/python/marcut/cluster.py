
from typing import Dict, Any, List, Tuple
from rapidfuzz import fuzz

LEGAL_SUFFIXES = ["inc","inc.","llc","l.l.c.","corp","corp.","co","co.","lp","l.p.","llp","l.l.p.","pllc","gmbh","s.a.","s.a","sa","ltd","ltd."]

def normalize(entity: str) -> str:
    x = entity.lower().replace("&","and")
    for suf in LEGAL_SUFFIXES:
        if x.endswith(" " + suf):
            x = x[:-(len(suf)+1)]
    x = "".join(ch for ch in x if ch.isalnum() or ch.isspace()).strip()
    while "  " in x: x = x.replace("  "," ")
    return x

class ClusterTable:
    def __init__(self):
        self.next_name = 1; self.next_org = 1; self.next_brand = 1
        self.clusters: Dict[str, List[Dict[str,Any]]] = {"NAME":[], "ORG":[], "BRAND":[]}

    def _new_id(self, label: str) -> str:
        if label == "NAME":
            k = f"NAME_{self.next_name}"; self.next_name += 1; return k
        if label == "ORG":
            k = f"ORG_{self.next_org}"; self.next_org += 1; return k
        k = f"BRAND_{self.next_brand}"; self.next_brand += 1; return k

    def link(self, label: str, surface: str) -> Tuple[str, float, bool]:
        n = normalize(surface)
        best = (None, 0.0)
        for cl in self.clusters[label]:
            for alias in cl["aliases"]:
                s = fuzz.token_set_ratio(n, alias) / 100.0
                if s > best[1]: best = (cl, s)
        if best[0] and (best[1] >= 0.82 or n in best[0]["aliases"]):
            best[0]["aliases"].add(n)
            return best[0]["id"], best[1], False
        cid = self._new_id(label)
        self.clusters[label].append({"id": cid, "aliases": {n}, "canonical": n})
        return cid, 1.0, True
