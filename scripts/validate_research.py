"""Run reproducible research acceptance queries through the real stdio protocol.

Outputs contain private library evidence. Write them outside version control.
This script does not contact external literature databases or modify the index.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CASES = {
    "alternative_oxidase": [
        '"alternative oxidase"',
        'AOX AND respiration',
        'alternative oxidase as a tool to study electron transport',
    ],
    "bax_bak_dynamics": [
        'BAX AND fusion OR BAK AND fusion OR BAX AND fission OR BAK AND fission',
        'BAX BAK mitochondrial fission fusion',
        'BAX BAK mitofusin',
    ],
}


async def run(args):
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["-m", "endnote_mcp.desktop_cli", "serve-desktop"]
    if args.config:
        command += ["--config", args.config]
    params = StdioServerParameters(command=sys.executable, args=command,
        env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
    report = {"transport": "stdio", "cases": {}, "details": {}, "page_reads": {}}
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as client:
            await client.initialize()
            report["tools"] = [t.name for t in (await client.list_tools()).tools]
            for label, queries in CASES.items():
                report["cases"][label] = []
                methods = ["search_references", "search_fulltext"]
                if args.semantic:
                    methods += ["search_semantic", "search_library"]
                for query in queries:
                    for tool in methods:
                        start = time.monotonic()
                        result = await asyncio.wait_for(client.call_tool(tool, {"query": query, "limit": 20}), 180)
                        data = result.structuredContent
                        if data is None:
                            data = {"text": [c.text for c in result.content if hasattr(c, "text")]}
                        report["cases"][label].append({"tool": tool, "query": query,
                            "seconds": round(time.monotonic()-start, 3), "is_error": result.isError, "result": data})
                        print(f'{label}: {tool}: {len(data.get("items", []))} results; error={data.get("error")}', flush=True)
                        output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
            for rec in args.records:
                result = await client.call_tool("get_reference_details", {"rec_number": rec})
                report["details"][str(rec)] = result.structuredContent
                if args.pages:
                    result = await client.call_tool("read_pdf_section", {"rec_number": rec, "start_page": 1, "end_page": args.pages})
                    report["page_reads"][str(rec)] = result.structuredContent
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Private validation output: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--output", required=True)
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--records", type=int, nargs="*", default=[])
    parser.add_argument("--pages", type=int, default=0)
    asyncio.run(run(parser.parse_args()))
