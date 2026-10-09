
import json
import math
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()

# Allow requests from dashboards on any origin.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the supplied telemetry file.
DATA_FILE = Path(__file__).resolve().parent.parent / "q-vercel-latency.json"

with open(DATA_FILE, "r", encoding="utf-8") as f:
    telemetry = json.load(f)


class AnalyticsRequest(BaseModel):
    regions: list[str]
    threshold_ms: float = Field(default=180, ge=0)


def get_records(data):
    """Support either a list of records or a dictionary containing records."""
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("records", "telemetry", "data", "pings"):
            if isinstance(data.get(key), list):
                return data[key]

    raise ValueError("Unrecognized telemetry JSON structure")


def percentile(values, percent):
    """Calculate a linearly interpolated percentile."""
    values = sorted(values)

    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return values[lower]

    return (
        values[lower] * (upper - position)
        + values[upper] * (position - lower)
    )


def get_value(record, keys):
    for key in keys:
        if key in record and record[key] is not None:
            return float(record[key])
    return None


@app.post("/")
@app.post("/api")
def analytics(request: AnalyticsRequest):
    try:
        records = get_records(telemetry)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    results = {}

    for region in request.regions:
        selected = [
            record for record in records
            if str(record.get("region", "")).lower() == region.lower()
        ]

        if not selected:
            raise HTTPException(
                status_code=400,
                detail=f"No telemetry records found for region: {region}",
            )

        latencies = []
        uptimes = []

        for record in selected:
            latency = get_value(
                record, ["latency_ms", "latency", "response_time_ms"]
            )
            uptime = get_value(
                record, ["uptime", "uptime_pct", "uptime_percent"]
            )

            if latency is None or uptime is None:
                raise HTTPException(
                    status_code=500,
                    detail="A record is missing latency or uptime data",
                )

            latencies.append(latency)
            uptimes.append(uptime)

        results[region] = {
            "avg_latency": sum(latencies) / len(latencies),
            "p95_latency": percentile(latencies, 95),
            "avg_uptime": sum(uptimes) / len(uptimes),
            "breaches": sum(
                latency > request.threshold_ms for latency in latencies
            ),
        }

    return results