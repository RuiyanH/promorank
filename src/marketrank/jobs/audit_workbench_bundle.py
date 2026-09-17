"""Scan browser-deliverable files against restricted identifiers and keys."""
import argparse
import re
from pathlib import Path

import duckdb

from marketrank.evidence import write_json


def audit(web_root:Path, store:Path|None=None) -> dict:
    roots=[web_root/"dist/client",web_root/"public"]
    if any(not root.is_dir() for root in roots):raise ValueError("build the browser bundle before auditing")
    forbidden={".parquet",".duckdb",".joblib",".key",".pt",".npz",".csv"}
    hex_strings,refs=set(),set()
    key_bytes=[]
    if store is not None:
        key_bytes=[p.read_bytes() for p in store.glob("*.key")]
    files=0;size=0
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():continue
            if path.suffix in forbidden:raise ValueError("restricted artifact extension in browser bundle")
            content=path.read_bytes();files+=1;size+=len(content)
            if b"PRIVATE KEY-----" in content or any(key in content or key.hex().encode() in content for key in key_bytes):
                raise ValueError("secret material in browser bundle")
            hex_strings.update(x.decode() for x in re.findall(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])",content))
            refs.update(x.decode() for x in re.findall(rb"v2c_[0-9a-f]{24}",content))
    if store is not None:
        with duckdb.connect(str(store/"restricted.duckdb"),read_only=True) as db:
            for values,table,column in ((hex_strings,"customers","customer_id"),(refs,"customer_refs","customer_key")):
                if values and db.execute(f"SELECT count(*) FROM {table} WHERE {column} IN (SELECT unnest(?))",[sorted(values)]).fetchone()[0]:
                    raise ValueError("restricted customer identifiers in browser bundle")
    return {"schema_version":"browser-bundle-audit.v2","files_scanned":files,"bytes_scanned":size,
        "restricted_extensions_found":0,"secret_material_found":0,
        "raw_and_internal_customer_scan":"passed" if store is not None else "not_run_no_restricted_store",
        "scope":"browser client output and public assets only; not a rewrite of legacy repository history"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--web-root",type=Path,default=Path("workbench"))
    p.add_argument("--store",type=Path)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();result=audit(a.web_root,a.store);write_json(a.out,result);print(result)
