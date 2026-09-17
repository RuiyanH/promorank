"""Audit an immutable release and benchmark a named local HTTP service."""
import argparse
import hashlib
import json
import platform
import resource
import statistics
import subprocess
import time
from pathlib import Path

import httpx

from marketrank.evidence import canonical, sha256, write_json
from marketrank.replay.release import verify_release, validate_recommendations


def run(release: Path, output: Path, base_url: str="http://127.0.0.1:8070"):
    if base_url!="http://127.0.0.1:8070":raise ValueError("runtime verification is loopback-only")
    started=time.perf_counter()
    manifest=verify_release(release)
    verification=time.perf_counter()-started
    prefix=f"/api/v2/releases/{manifest['release_id']}"
    with httpx.Client(base_url=base_url,timeout=30) as client:
        assert client.get("/health/ready").json()["release_id"]==manifest["release_id"]
        customers=client.get(prefix+"/customers",params={"limit":100}).json()["customers"]
        paths=[prefix+f"/customers/{c['customer_ref']}/recommendations?as_of={day}"
               for c in customers for day in manifest["dates"]]
        paths += [prefix+"/customers?limit=25",prefix+"/customers?q=00001&limit=25",prefix+"/quality"]*10
        for path in paths[:10]:client.get(path).raise_for_status()
        elapsed=[]
        for path in paths:
            start=time.perf_counter();response=client.get(path);elapsed.append((time.perf_counter()-start)*1000)
            response.raise_for_status()
            if "/recommendations?" in path:validate_recommendations(response.json())
            if response.headers.get("cache-control")!="no-store":raise ValueError("missing privacy cache policy")
        assert client.get(prefix+"/customers",params={"limit":101}).status_code==422
        assert client.get(prefix+"/customers/invalid/recommendations?as_of=2020-09-09").status_code==404
        assert client.post(prefix+"/customers").status_code==405
    cpu=platform.processor()
    if platform.system()=="Darwin":cpu=subprocess.check_output(["sysctl","-n","machdep.cpu.brand_string"],text=True).strip()
    report={"schema_version":"replay-runtime-verification.v2","release_manifest_sha256":sha256(release/"manifest.json"),
        "platform":platform.platform(),"processor":cpu,"python":platform.python_version(),
        "release_verification_seconds":verification,"verification_peak_rss_platform_units":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "database_bytes":(release/"replay.duckdb").stat().st_size,
        "requests":len(paths),"request_set_sha256":hashlib.sha256(canonical(paths)).hexdigest(),
        "workload":"first 100 label-ordered customers on both dates; 10 each listing/search/quality; sequential keep-alive HTTP; 10 warmups",
        "warm_p50_ms":statistics.median(elapsed),"warm_p95_ms":statistics.quantiles(elapsed,n=100,method="inclusive")[94],
        "warm_max_ms":max(elapsed),"threshold_ms":500,
        "performance_passed":statistics.quantiles(elapsed,n=100,method="inclusive")[94]<500}
    write_json(output,report);print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();run(a.release,a.out)
