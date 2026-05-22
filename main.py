from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
import psutil
import cpuinfo
import platform
import sys
import time
import math
import wmi
import json

from datetime import datetime

console = Console()


def show_banner():
    console.print(
        Panel.fit(
            "[bold cyan]CPU Sentinel CLI[/bold cyan]\n"
            "CPU Health, Benchmark, Stress Test & Diagnostics",
            border_style="cyan"
        )
    )


def get_cpu_temperature():
    try:
        temps, _ = get_lhm_sensors()

        if temps:
            cpu_temps = []

            for temp in temps:
                if "CPU" in temp["name"] or "Core" in temp["name"]:
                    cpu_temps.append(temp["value"])

            if cpu_temps:
                return max(cpu_temps)

        return None

    except Exception:
        return None

def get_lhm_sensors():
    try:
        w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
        sensors = w.Sensor()

        temps = []
        fans = []

        for sensor in sensors:

            if sensor.SensorType == "Temperature":
                temps.append({
                    "name": sensor.Name,
                    "value": sensor.Value
                })

            elif sensor.SensorType == "Fan":
                fans.append({
                    "name": sensor.Name,
                    "value": sensor.Value
                })

        return temps, fans

    except Exception:
        return [], []
    
def show_sensors():

    temps, fans = get_lhm_sensors()

    if not temps and not fans:
        console.print(
            "[bold red]No hardware sensors detected.[/bold red]\n"
            "Make sure LibreHardwareMonitor is:\n"
            "- Running\n"
            "- Opened as Administrator\n"
            "- WMI enabled"
        )
        return

    table = Table(title="Hardware Sensors")

    table.add_column("Type", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Value", style="yellow")

    for temp in temps:

        status = "Good"

        if temp["value"] >= 90:
            status = "Critical"
        elif temp["value"] >= 80:
            status = "Hot"

        table.add_row(
            "Temperature",
            temp["name"],
            f"{temp['value']} °C [{status}]"
        )

    for fan in fans:

        table.add_row(
            "Fan",
            fan["name"],
            f"{temp['value']} RPM"
        )

    console.print(table)

def show_task_manager():
    ram = psutil.virtual_memory()

    ram_table = Table(title="RAM Usage")
    ram_table.add_column("Metric", style="cyan")
    ram_table.add_column("Value", style="green")

    ram_table.add_row("Total RAM", f"{round(ram.total / (1024 ** 3), 2)} GB")
    ram_table.add_row("Used RAM", f"{round(ram.used / (1024 ** 3), 2)} GB")
    ram_table.add_row("Available RAM", f"{round(ram.available / (1024 ** 3), 2)} GB")
    ram_table.add_row("RAM Usage", f"{ram.percent}%")

    console.print(ram_table)

    # First call initializes CPU percentage measurement
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent(interval=None)
        except Exception:
            pass

    time.sleep(1)

    process_table = Table(title="Open Processes")
    process_table.add_column("PID", style="cyan")
    process_table.add_column("Process Name", style="green")
    process_table.add_column("CPU %", style="yellow")
    process_table.add_column("RAM %", style="magenta")
    process_table.add_column("RAM MB", style="blue")

    processes = []

    for proc in psutil.process_iter(["pid", "name", "memory_percent", "memory_info"]):
        try:
            cpu_percent = proc.cpu_percent(interval=None)
            memory_percent = proc.info["memory_percent"]
            memory_mb = proc.info["memory_info"].rss / (1024 ** 2)

            processes.append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "cpu": cpu_percent,
                "ram_percent": memory_percent,
                "ram_mb": memory_mb
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    processes = sorted(processes, key=lambda x: x["cpu"], reverse=True)[:25]

    for p in processes:
        process_table.add_row(
            str(p["pid"]),
            str(p["name"]),
            f"{round(p['cpu'], 2)}%",
            f"{round(p['ram_percent'], 2)}%",
            f"{round(p['ram_mb'], 2)} MB"
        )

    console.print(process_table)


def evaluate_cpu_health(usage, temperature=None, throttling=False, stability_score=100):
    score = 100
    warnings = []

    if usage >= 90:
        score -= 25
        warnings.append("Very high CPU usage")
    elif usage >= 75:
        score -= 15
        warnings.append("High CPU usage")
    elif usage >= 50:
        score -= 5
        warnings.append("Moderate CPU usage")

    if temperature is not None:
        if temperature >= 95:
            score -= 40
            warnings.append("Critical overheating")
        elif temperature >= 85:
            score -= 25
            warnings.append("Very hot CPU")
        elif temperature >= 75:
            score -= 10
            warnings.append("CPU is getting hot")
    else:
        warnings.append("Temperature sensor unavailable")

    if throttling:
        score -= 25
        warnings.append("Possible thermal throttling detected")

    if stability_score < 70:
        score -= 20
        warnings.append("Low stability score")
    elif stability_score < 85:
        score -= 10
        warnings.append("Moderate stability score")

    score = max(0, min(100, score))

    if score >= 90:
        status = "Excellent"
    elif score >= 75:
        status = "Good"
    elif score >= 60:
        status = "Fair"
    elif score >= 40:
        status = "Poor"
    else:
        status = "Critical"

    return score, status, warnings


def detect_throttling(duration=5):
    freq = psutil.cpu_freq()

    if not freq or not freq.max or freq.max <= 0:
        return False, "Cannot check throttling because max CPU frequency is unavailable."

    low_frequency_count = 0
    samples = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Checking throttling..."),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("throttle", total=duration)

        for _ in range(duration):
            usage = psutil.cpu_percent(interval=1)
            freq = psutil.cpu_freq()

            if freq:
                percent = (freq.current / freq.max) * 100
                samples.append(percent)

                if usage > 70 and percent < 65:
                    low_frequency_count += 1

            progress.advance(task)

    if low_frequency_count >= 3:
        return True, "Possible throttling detected."

    avg = round(sum(samples) / len(samples), 2) if samples else 0
    return False, f"No clear throttling detected. Avg frequency: {avg}% of max."


def run_cpu_benchmark(seconds=5):
    operations = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Running benchmark..."),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("benchmark", total=seconds)

        start = time.time()
        last_second = 0

        while time.time() - start < seconds:
            for i in range(1, 5000):
                math.sqrt(i) * math.sin(i)
                operations += 1

            elapsed = int(time.time() - start)

            if elapsed > last_second:
                progress.advance(task)
                last_second = elapsed

    return round(operations / seconds)


def show_cpu_health():
    cpu = cpuinfo.get_cpu_info()
    usage = psutil.cpu_percent(interval=1)
    temp = get_cpu_temperature()
    throttling, throttle_msg = detect_throttling()
    stability = run_stability_test(seconds=5)

    score, status, warnings = evaluate_cpu_health(
        usage,
        temp,
        throttling,
        stability
    )

    table = Table(title="CPU Health Evaluation")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Status", style="bold")

    table.add_row("CPU Model", cpu.get("brand_raw", "Unknown"), "Detected")
    table.add_row("OS", platform.system(), "Detected")
    table.add_row("Architecture", cpu.get("arch", "Unknown"), "Detected")
    table.add_row("Physical Cores", str(psutil.cpu_count(logical=False)), "OK")
    table.add_row("Logical Threads", str(psutil.cpu_count(logical=True)), "OK")
    table.add_row("CPU Usage", f"{usage}%", "OK")

    freq = psutil.cpu_freq()
    if freq:
        table.add_row("Current Frequency", f"{round(freq.current, 2)} MHz", "Running")
        table.add_row("Max Frequency", f"{round(freq.max, 2)} MHz", "Supported")

    table.add_row("Temperature", f"{temp} °C" if temp else "Unavailable", "OK" if temp else "Unknown")
    table.add_row("Throttling", throttle_msg, "Warning" if throttling else "OK")
    table.add_row("Stability Score", f"{stability}/100", "OK")
    table.add_row("Overall Health Score", f"{score}/100", status)

    console.print(table)

    if warnings:
        console.print(Panel("\n".join(f"- {w}" for w in warnings), title="Warnings", border_style="yellow"))
    else:
        console.print(Panel("No major CPU issues detected.", border_style="green"))


def show_benchmark():
    console.print("[yellow]Running benchmark...[/yellow]")
    score = run_cpu_benchmark()

    table = Table(title="CPU Benchmark")
    table.add_column("Test")
    table.add_column("Score")

    table.add_row("Math Operations Benchmark", f"{score} ops/sec")

    console.print(table)


def show_live_monitor():
    console.print("[green]Live monitor started. Press CTRL + C to stop.[/green]")

    try:
        while True:
            console.clear()
            usage = psutil.cpu_percent(interval=1)
            freq = psutil.cpu_freq()
            temp = get_cpu_temperature()

            table = Table(title="Live CPU Monitor")
            table.add_column("Metric")
            table.add_column("Value")

            table.add_row("CPU Usage", f"{usage}%")

            if freq:
                table.add_row("Current Frequency", f"{round(freq.current, 2)} MHz")

            table.add_row("Temperature", f"{temp} °C" if temp else "Unavailable")

            console.print(table)
            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[red]Live monitor stopped.[/red]")


def show_temperature():
    temp = get_cpu_temperature()

    if temp:
        console.print(f"[bold cyan]CPU Temperature:[/bold cyan] {temp} °C")
    else:
        console.print("[yellow]CPU temperature unavailable on this system.[/yellow]")


def run_stress_test(seconds=10):
    operations = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[red]Running CPU stress test..."),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("stress", total=seconds)

        start = time.time()
        last_second = 0

        while time.time() - start < seconds:
            for i in range(1, 10000):
                math.sqrt(i) * math.sin(i) * math.cos(i)
                operations += 1

            elapsed = int(time.time() - start)

            if elapsed > last_second:
                progress.advance(task)
                last_second = elapsed

    console.print(f"[green]Stress test finished.[/green] Operations: {operations}")


def show_cache_info():
    cpu = cpuinfo.get_cpu_info()

    table = Table(title="CPU Cache Information")
    table.add_column("Cache")
    table.add_column("Value")

    table.add_row("L1 Data Cache", str(cpu.get("l1_data_cache_size", "Unknown")))
    table.add_row("L1 Instruction Cache", str(cpu.get("l1_instruction_cache_size", "Unknown")))
    table.add_row("L2 Cache", str(cpu.get("l2_cache_size", "Unknown")))
    table.add_row("L3 Cache", str(cpu.get("l3_cache_size", "Unknown")))

    console.print(table)


def show_processes():
    processes = []

    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            processes.append(proc.info)
        except Exception:
            pass

    processes = sorted(processes, key=lambda p: p["cpu_percent"], reverse=True)[:10]

    table = Table(title="Top CPU Processes")
    table.add_column("PID")
    table.add_column("Name")
    table.add_column("CPU %")
    table.add_column("Memory %")

    for p in processes:
        table.add_row(
            str(p["pid"]),
            str(p["name"]),
            str(p["cpu_percent"]),
            str(round(p["memory_percent"], 2))
        )

    console.print(table)


def show_battery():
    battery = psutil.sensors_battery()

    if not battery:
        console.print("[yellow]Battery information unavailable.[/yellow]")
        return

    table = Table(title="Battery Information")
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("Battery Percent", f"{battery.percent}%")
    table.add_row("Charging", "Yes" if battery.power_plugged else "No")

    console.print(table)


def show_gpu():
    console.print("[yellow]GPU monitoring is not available yet.[/yellow]")
    console.print("Later you can add GPUtil or LibreHardwareMonitor support.")

def run_stability_test(seconds=10):
    usage_samples = []
    freq_samples = []
    temp_samples = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Running stability test..."),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task("stability", total=seconds)

        for _ in range(seconds):
            usage = psutil.cpu_percent(interval=1)
            freq = psutil.cpu_freq()
            temp = get_cpu_temperature()

            usage_samples.append(usage)

            if freq:
                freq_samples.append(freq.current)

            if temp:
                temp_samples.append(temp)

            progress.advance(task)

    score = 100

    if freq_samples:
        freq_drop = max(freq_samples) - min(freq_samples)

        if freq_drop > 1000:
            score -= 20
        elif freq_drop > 500:
            score -= 10

    if temp_samples:
        max_temp = max(temp_samples)

        if max_temp >= 95:
            score -= 40
        elif max_temp >= 85:
            score -= 25
        elif max_temp >= 75:
            score -= 10

    return max(0, score)


def show_compare():
    score = run_cpu_benchmark()

    if score > 900000:
        result = "Very strong CPU performance"
    elif score > 500000:
        result = "Good CPU performance"
    elif score > 250000:
        result = "Average CPU performance"
    else:
        result = "Weak CPU performance"

    console.print(Panel(f"Benchmark Score: {score} ops/sec\nResult: {result}", title="CPU Compare"))


def export_report():
    usage = psutil.cpu_percent(interval=1)
    temp = get_cpu_temperature()
    throttling, throttle_msg = detect_throttling(duration=3)
    stability = run_stability_test(seconds=3)
    score, status, warnings = evaluate_cpu_health(usage, temp, throttling, stability)

    report = {
        "date": str(datetime.now()),
        "cpu": cpuinfo.get_cpu_info().get("brand_raw", "Unknown"),
        "os": platform.system(),
        "cpu_usage": usage,
        "temperature": temp,
        "throttling": throttle_msg,
        "stability_score": stability,
        "health_score": score,
        "health_status": status,
        "warnings": warnings
    }

    with open("cpu_report.json", "w") as file:
        json.dump(report, file, indent=4)

    console.print("[green]Report exported to cpu_report.json[/green]")


def diagnose():
    usage = psutil.cpu_percent(interval=1)
    temp = get_cpu_temperature()
    throttling, throttle_msg = detect_throttling(duration=3)

    issues = []

    if usage > 80:
        issues.append("High CPU usage detected.")

    if temp and temp > 85:
        issues.append("CPU temperature is very high.")

    if throttling:
        issues.append("Possible throttling detected.")

    if not temp:
        issues.append("Temperature sensor unavailable.")

    if not issues:
        issues.append("No major issues detected.")

    console.print(Panel("\n".join(f"- {i}" for i in issues), title="Diagnosis"))


def show_help():
    console.print("[bold cyan]Available Commands[/bold cyan]\n")

    console.print("cpus health       Full CPU health evaluation")
    console.print("cpus benchmark    Run CPU benchmark")
    console.print("cpus live         Live CPU monitor")
    console.print("cpus temp         Show CPU temperature")
    console.print("cpus stress       Run CPU stress test")
    console.print("cpus cache        Show CPU cache info")
    console.print("cpus compare      Compare CPU performance")
    console.print("cpus export       Export CPU report to JSON")
    console.print("cpus gpu          Show GPU placeholder info")
    console.print("cpus battery      Show battery info")
    console.print("cpus processes    Show top CPU processes")
    console.print("cpus diagnose     Detect possible CPU issues")
    console.print("cpus help         Show help")
    console.print("cpus sensors      Show temperatures and fan speeds")
    console.print("cpus taskmgr      Show RAM usage and open processes")


def main():
    show_banner()

    if len(sys.argv) < 2:
        show_help()
        return

    command = sys.argv[1].lower()

    if command == "health":
        show_cpu_health()
    elif command == "benchmark":
        show_benchmark()
    elif command == "live":
        show_live_monitor()
    elif command == "temp":
        show_temperature()
    elif command == "stress":
        run_stress_test()
    elif command == "cache":
        show_cache_info()
    elif command == "compare":
        show_compare()
    elif command == "export":
        export_report()
    elif command == "gpu":
        show_gpu()
    elif command == "battery":
        show_battery()
    elif command == "processes":
        show_processes()
    elif command == "diagnose":
        diagnose()
    elif command == "help":
        show_help()
    elif command == "sensors":
        show_sensors()
    elif command == "taskmgr":
        show_task_manager()
    else:
        console.print(f"[bold red]Unknown command:[/bold red] {command}")
        show_help()


main()