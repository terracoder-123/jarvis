"""System utilities — time, diagnostics."""

import datetime
import platform
import shutil


async def get_current_time():
    """Return the current date and time."""
    now = datetime.datetime.now()
    return {
        "local_time": now.strftime("%I:%M %p"),
        "local_date": now.strftime("%A, %B %d, %Y"),
        "iso": now.isoformat(),
        "timezone": str(now.astimezone().tzinfo),
    }


async def run_diagnostics():
    """Run basic system diagnostics — OS, CPU, disk."""
    report = {
        "os": f"{platform.system()} {platform.release()}",
        "hostname": platform.node(),
        "python": platform.python_version(),
        "machine": platform.machine(),
    }
    try:
        import multiprocessing
        report["cpu_cores"] = multiprocessing.cpu_count()
    except Exception:
        pass
    try:
        total, used, free = shutil.disk_usage("/")
        pct = round(used / total * 100, 1)
        report["disk_free_gb"] = round(free / (1024 ** 3), 1)
        report["disk_total_gb"] = round(total / (1024 ** 3), 1)
        report["disk_used_percent"] = pct
        report["disk_status"] = "Warning: low space" if pct > 85 else "Nominal"
    except Exception:
        pass
    report["overall"] = "All systems nominal" if report.get("disk_status", "").startswith("Nominal") else "Minor warnings"
    return report


DECLARATIONS = [
    {
        "name": "get_current_time",
        "description": "Get the current date and time. Use when the user asks 'what time is it' or 'what's the date'.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "run_diagnostics",
        "description": "Run system diagnostics — OS, CPU, disk usage. Use when the user asks for diagnostics, system status, or 'run a check'.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]
