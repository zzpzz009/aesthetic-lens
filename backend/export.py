"""
export.py — CSV / JSON 结果导出
"""

import csv
import json
from datetime import datetime
from pathlib import Path


def export_csv(results: list[dict], output_path: str):
    """
    导出评分结果为 CSV

    Args:
        results: [{"filename": ..., "score": ..., "tier": ..., "error": ...}, ...]
        output_path: 输出路径
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["文件名", "美学评分", "等级", "错误"])
        for r in results:
            writer.writerow([
                r.get("filename", ""),
                r.get("score", ""),
                r.get("tier", ""),
                r.get("error", ""),
            ])


def export_json(results: list[dict], output_path: str):
    """导出评分结果为 JSON"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    export_data = {
        "export_time": datetime.now().isoformat(),
        "total": len(results),
        "results": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
