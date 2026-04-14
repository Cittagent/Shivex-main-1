from datetime import datetime

from jinja2 import Template
from zoneinfo import ZoneInfo

from src.pdf import charts
from src.utils.localization import format_platform_timestamp


def _render_pdf(html_content: str) -> bytes:
    try:
        from weasyprint import HTML as WeasyHTML
    except Exception as exc:
        raise RuntimeError(
            "WeasyPrint is required to render PDF reports. "
            "Install the native WeasyPrint dependencies before generating a report."
        ) from exc

    return WeasyHTML(string=html_content).write_pdf()


def generate_consumption_pdf(data: dict) -> bytes:
    daily_series = data.get("daily_series", [])
    per_device = data.get("per_device", [])

    charts_dict = {}
    if daily_series:
        charts_dict["daily_energy"] = charts.daily_energy_bar_chart(daily_series)
    if per_device:
        charts_dict["device_share"] = charts.device_share_donut(per_device)

    data["charts"] = charts_dict
    data["report_theme_class"] = "theme-energy"
    data["generated_at"] = format_platform_timestamp(datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")))
    data["peak_timestamp"] = format_platform_timestamp(data.get("peak_timestamp"))
    data["tariff_fetched_at"] = format_platform_timestamp(data.get("tariff_fetched_at"))

    html_content = Template(get_consumption_report_template()).render(**data)
    return _render_pdf(html_content)


def generate_comparison_pdf(data: dict) -> bytes:
    comparison = data.get("comparison", {})
    metrics = comparison.get("metrics", {})

    if metrics:
        data["comparison_chart"] = charts.comparison_bar_chart(metrics)

    data["report_theme_class"] = "theme-comparison"
    data["generated_at"] = format_platform_timestamp(datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")))

    html_content = Template(get_comparison_report_template()).render(**data)
    return _render_pdf(html_content)


def _report_styles() -> str:
    return """
    <style>
        @page {
            size: A4;
            margin: 1.05cm;
        }

        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            font-size: 10px;
            line-height: 1.45;
            color: #172033;
            background: #eef3f8;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }

        .theme-energy {
            --accent: #2563eb;
            --accent-soft: #dbeafe;
            --accent-2: #0f766e;
            --accent-ink: #12316b;
            --tint: #f4f8ff;
        }

        .theme-comparison {
            --accent: #0f766e;
            --accent-soft: #dff7f1;
            --accent-2: #2563eb;
            --accent-ink: #11423c;
            --tint: #f2fbf8;
        }

        .page {
            background: #ffffff;
            border: 1px solid #dce5f0;
            border-radius: 22px;
            box-shadow: 0 18px 48px rgba(15, 23, 42, 0.08);
            overflow: hidden;
        }

        .hero {
            padding: 24px 24px 20px;
            color: #ffffff;
            background:
                radial-gradient(circle at top right, rgba(255, 255, 255, 0.16), transparent 34%),
                linear-gradient(140deg, #0f172a 0%, var(--accent-ink) 44%, var(--accent) 100%);
        }

        .hero-topbar {
            display: table;
            width: 100%;
            table-layout: fixed;
            margin-bottom: 18px;
        }

        .hero-brand,
        .hero-stamp {
            display: table-cell;
            vertical-align: top;
        }

        .hero-brand {
            width: 68%;
        }

        .hero-stamp {
            width: 32%;
            text-align: right;
        }

        .brand-kicker {
            font-size: 8px;
            text-transform: uppercase;
            letter-spacing: 2.2px;
            color: rgba(255, 255, 255, 0.72);
            margin-bottom: 6px;
        }

        .brand-name {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: 0.8px;
        }

        .hero-stamp > div {
            display: inline-block;
            min-width: 116px;
            padding: 9px 12px;
            border-radius: 14px;
            text-align: left;
            background: rgba(255, 255, 255, 0.11);
            border: 1px solid rgba(255, 255, 255, 0.16);
        }

        .stamp-label {
            font-size: 7.5px;
            text-transform: uppercase;
            letter-spacing: 1.3px;
            color: rgba(255, 255, 255, 0.72);
            margin-bottom: 4px;
        }

        .stamp-value {
            font-size: 9.5px;
            font-weight: 600;
            line-height: 1.35;
        }

        .hero h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }

        .hero-subtitle {
            margin-top: 8px;
            max-width: 74%;
            font-size: 11px;
            line-height: 1.55;
            color: rgba(255, 255, 255, 0.88);
        }

        .hero-caption {
            margin-top: 14px;
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 1.4px;
            color: rgba(255, 255, 255, 0.72);
        }

        .hero-meta {
            display: table;
            width: 100%;
            table-layout: fixed;
            margin-top: 16px;
            border-collapse: separate;
            border-spacing: 8px 0;
        }

        .meta-chip {
            display: table-cell;
            width: 25%;
            vertical-align: top;
        }

        .meta-chip > div {
            min-height: 60px;
            padding: 10px 11px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.11);
            border: 1px solid rgba(255, 255, 255, 0.14);
        }

        .meta-label {
            display: block;
            font-size: 7.8px;
            text-transform: uppercase;
            letter-spacing: 1.1px;
            color: rgba(255, 255, 255, 0.72);
            margin-bottom: 5px;
        }

        .meta-value {
            display: block;
            font-size: 10.5px;
            font-weight: 600;
            color: #ffffff;
            word-break: break-word;
            line-height: 1.45;
        }

        .content {
            padding: 18px;
        }

        .section {
            margin-bottom: 14px;
            break-inside: avoid;
            page-break-inside: avoid;
            border: 1px solid #e3eaf3;
            border-radius: 18px;
            background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
            padding: 16px;
        }

        .section-title-row {
            display: table;
            width: 100%;
            margin-bottom: 10px;
        }

        .section-title-row h2 {
            display: table-cell;
            width: 70%;
            margin: 0;
            font-size: 15px;
            letter-spacing: -0.2px;
            color: #0f172a;
        }

        .section-subtitle {
            display: table-cell;
            width: 30%;
            text-align: right;
            color: #64748b;
            font-size: 8.5px;
            vertical-align: bottom;
            letter-spacing: 0.3px;
        }

        .section-kicker {
            display: inline-block;
            margin-bottom: 7px;
            font-size: 7.8px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--accent);
        }

        .section-intro {
            margin: 0 0 12px;
            font-size: 9.5px;
            color: #5b6678;
        }

        .kpi-grid {
            display: table;
            width: 100%;
            table-layout: fixed;
            border-spacing: 10px 0;
        }

        .kpi-card {
            display: table-cell;
            width: 25%;
            padding: 13px 13px 12px;
            border-radius: 16px;
            background: linear-gradient(180deg, var(--tint) 0%, #ffffff 100%);
            border: 1px solid #d9e5f4;
            vertical-align: top;
        }

        .kpi-label {
            font-size: 7.8px;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            color: #64748b;
            margin-bottom: 7px;
        }

        .kpi-value {
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-ink);
            line-height: 1.15;
            letter-spacing: -0.4px;
        }

        .kpi-note {
            margin-top: 7px;
            font-size: 8.3px;
            color: #64748b;
        }

        .summary-strip {
            display: table;
            width: 100%;
            table-layout: fixed;
            border-spacing: 10px 0;
            margin-top: 10px;
        }

        .summary-item {
            display: table-cell;
            width: 25%;
            padding: 11px 12px;
            border-radius: 14px;
            background: #f8fbff;
            border: 1px solid #e1eaf5;
            color: #334155;
            font-size: 8.8px;
            vertical-align: top;
        }

        .summary-item strong {
            display: block;
            font-size: 9.5px;
            color: #0f172a;
            margin-bottom: 4px;
        }

        .two-col {
            display: table;
            width: 100%;
            table-layout: fixed;
            border-spacing: 10px 0;
        }

        .two-col-cell {
            display: table-cell;
            width: 50%;
            vertical-align: top;
        }

        .spotlight-card,
        .callout-card {
            min-height: 100%;
            padding: 14px;
            border-radius: 16px;
            border: 1px solid #dce6f3;
            background: #ffffff;
        }

        .spotlight-card {
            background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
        }

        .spotlight-label {
            font-size: 7.8px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.3px;
            color: var(--accent);
            margin-bottom: 7px;
        }

        .spotlight-value {
            font-size: 22px;
            font-weight: 700;
            line-height: 1.12;
            color: #0f172a;
        }

        .spotlight-note {
            margin-top: 8px;
            font-size: 8.6px;
            color: #5d6778;
        }

        .callout-card h3 {
            margin: 0 0 8px;
            font-size: 12px;
            color: #0f172a;
        }

        .callout-card p {
            margin: 0;
            color: #536072;
            font-size: 9.2px;
            line-height: 1.55;
        }

        .badge {
            display: inline-block;
            padding: 4px 9px;
            border-radius: 999px;
            font-size: 7.8px;
            font-weight: 700;
            letter-spacing: 0.8px;
            text-transform: uppercase;
        }

        .badge-good {
            background: #dcfce7;
            color: #166534;
        }

        .badge-medium {
            background: #fef3c7;
            color: #92400e;
        }

        .badge-low {
            background: #fee2e2;
            color: #991b1b;
        }

        .badge-muted {
            background: #e2e8f0;
            color: #334155;
        }

        .badge-danger {
            background: #fee2e2;
            color: #991b1b;
        }

        .badge-success-soft {
            background: #dcfce7;
            color: #166534;
        }

        .notice {
            margin-top: 10px;
            padding: 10px 12px;
            border-radius: 12px;
            background: #eff6ff;
            border: 1px solid #d2e4ff;
            color: #1e3a8a;
            font-size: 8.9px;
        }

        .warning {
            margin-top: 10px;
            padding: 10px 12px;
            border-radius: 12px;
            background: #fff7ed;
            border: 1px solid #fed7aa;
            color: #9a3412;
            font-size: 8.9px;
        }

        .error {
            margin-top: 10px;
            padding: 10px 12px;
            border-radius: 12px;
            background: #fef2f2;
            border: 1px solid #fecaca;
            color: #991b1b;
            font-size: 8.9px;
        }

        .chart-row {
            display: table;
            width: 100%;
            table-layout: fixed;
            border-spacing: 10px 0;
        }

        .chart-col {
            display: table-cell;
            width: 50%;
            vertical-align: top;
        }

        .chart-card {
            padding: 12px;
            border-radius: 16px;
            border: 1px solid #dce6f3;
            background: linear-gradient(180deg, #ffffff 0%, #f9fbff 100%);
            text-align: center;
        }

        .chart-title {
            margin-bottom: 9px;
            text-align: left;
            font-size: 10px;
            font-weight: 700;
            color: #172033;
        }

        .chart-card img {
            width: 100%;
            max-width: 100%;
            max-height: 240px;
            object-fit: contain;
        }

        .table-wrap {
            overflow: hidden;
            border-radius: 16px;
            border: 1px solid #dce6f3;
            background: #ffffff;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        thead th {
            background: #f7faff;
            color: #4a5870;
            font-size: 7.8px;
            text-transform: uppercase;
            letter-spacing: 1px;
            border-bottom: 1px solid #dce6f3;
        }

        th,
        td {
            padding: 9px 10px;
            border-bottom: 1px solid #e7edf5;
            text-align: left;
            font-size: 8.9px;
            vertical-align: top;
        }

        tbody tr:nth-child(even) {
            background: #fbfdff;
        }

        .right,
        .align-right,
        .numeric,
        .financial {
            text-align: right;
            white-space: nowrap;
        }

        .muted {
            color: #64748b;
        }

        .overtime-table .overtime-row {
            background: #fff1f2;
        }

        .overtime-table .overtime-row td {
            color: #7f1d1d;
        }

        .overtime-table .zero-row td {
            color: #334155;
        }

        .overtime-summary-card {
            width: 33.333%;
        }

        .overtime-note {
            margin-top: 8px;
            font-size: 9px;
            color: #7f1d1d;
        }

        .insight-list {
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .insight-list li {
            margin-top: 8px;
            padding: 10px 12px;
            border-radius: 12px;
            background: #f8fbff;
            border: 1px solid #dbe7f7;
            color: #0f172a;
            font-size: 8.9px;
        }

        .footer {
            margin-top: 10px;
            padding: 12px 4px 0;
            border-top: 1px solid #e7edf5;
            text-align: center;
            font-size: 8px;
            color: #738095;
        }

        .footer strong {
            color: #0f172a;
        }

        .page-break {
            page-break-before: always;
        }
    </style>
    """


def get_consumption_report_template():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Energy Consumption Report</title>
    """ + _report_styles() + """
</head>
<body class="{{ report_theme_class }}">
    <div class="page">
        <div class="hero">
            <div class="hero-topbar">
                <div class="hero-brand">
                    <div class="brand-kicker">Shivex Energy Intelligence</div>
                    <div class="brand-name">Consumption Report</div>
                </div>
                <div class="hero-stamp">
                    <div>
                        <div class="stamp-label">Generated</div>
                        <div class="stamp-value">{{ generated_at }}</div>
                    </div>
                </div>
            </div>
            <h1>Energy Consumption Report</h1>
            <div class="hero-subtitle">
                A polished operational summary of energy use, cost drivers, load behaviour, and overtime exposure for the selected reporting window.
            </div>
            <div class="hero-caption">Scope: {{ device_label }} | Period: {{ start_date }} to {{ end_date }}</div>
            <div class="hero-meta">
                <div class="meta-chip"><div><span class="meta-label">Report ID</span><span class="meta-value">{{ report_id }}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Data Quality</span><span class="meta-value">{{ overall_quality|title }}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Tariff</span><span class="meta-value">{% if tariff_rate_used is not none %}{{ currency }} {{ tariff_rate_used }} / kWh{% else %}Not configured{% endif %}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Peak Timestamp</span><span class="meta-value">{% if peak_timestamp and peak_timestamp != "N/A" %}{{ peak_timestamp }}{% else %}N/A{% endif %}</span></div></div>
            </div>
        </div>

        <div class="content">
            <div class="section">
                <div class="section-kicker">Executive Overview</div>
                <div class="section-title-row">
                    <h2>Executive Summary</h2>
                    <div class="section-subtitle">
                        {% if overall_quality != "high" %}Estimated telemetry detected{% else %}High-confidence telemetry{% endif %}
                    </div>
                </div>
                <p class="section-intro">This page highlights total consumption, demand pressure, financial exposure, and the quality of the telemetry used to build the report.</p>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Total Energy</div>
                        <div class="kpi-value">{{ total_kwh }} kWh</div>
                        <div class="kpi-note">Across selected devices</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Peak Demand</div>
                        <div class="kpi-value">{% if peak_demand_kw is not none %}{{ peak_demand_kw }} kW{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if peak_timestamp and peak_timestamp != "N/A" %}{{ peak_timestamp }}{% else %}Peak timestamp unavailable{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Load Factor</div>
                        <div class="kpi-value">{% if load_factor_pct is not none %}{{ load_factor_pct }}%{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if average_load_kw is not none %}Avg load {{ average_load_kw }} kW{% else %}Average load unavailable{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Total Cost</div>
                        <div class="kpi-value">{% if total_cost is not none %}{{ currency }} {{ total_cost }}{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if tariff_rate_used is not none %}{{ currency }} {{ tariff_rate_used }} / kWh{% else %}Cost estimation skipped{% endif %}</div>
                    </div>
                </div>

                <div class="summary-strip">
                    <div class="summary-item"><strong>Average Load</strong>{% if average_load_kw is not none %}{{ average_load_kw }} kW{% else %}N/A{% endif %}</div>
                    <div class="summary-item"><strong>Devices</strong>{{ per_device|length }} device{% if per_device|length != 1 %}s{% endif %}</div>
                    <div class="summary-item"><strong>Tariff Snapshot</strong>{% if tariff_fetched_at and tariff_fetched_at != "N/A" %}{{ tariff_fetched_at }}{% else %}Not recorded{% endif %}</div>
                </div>

                <div class="spotlight-card" style="margin-top: 10px;">
                    <div class="spotlight-label">Primary Cost Driver</div>
                    <div class="spotlight-value">{% if total_cost is not none %}{{ currency }} {{ total_cost }}{% else %}Tariff missing{% endif %}</div>
                    <div class="spotlight-note">
                        {% if tariff_rate_used is not none %}
                        Cost estimate based on {{ currency }} {{ tariff_rate_used }} per kWh for the selected period.
                        {% else %}
                        Configure a tariff to unlock financial calculations in future reports.
                        {% endif %}
                    </div>
                </div>

                {% if overall_quality != "high" %}
                <div class="notice">Some values are estimated because telemetry coverage was incomplete. The detailed sections below call out the affected devices and days.</div>
                {% endif %}
                {% if peak_timestamp and peak_timestamp != "N/A" %}
                <div class="notice">Peak demand timestamp: {{ peak_timestamp }}</div>
                {% endif %}
            </div>

            <div class="section">
                <div class="section-kicker">Performance Shape</div>
                <div class="section-title-row">
                    <h2>Trend and Energy Share</h2>
                    <div class="section-subtitle">Daily pattern and device distribution</div>
                </div>
                <p class="section-intro">These charts show how energy moved across the reporting period and how the selected devices contributed to the total load.</p>
                <div class="chart-row">
                    <div class="chart-col">
                        <div class="chart-card">
                            <div class="chart-title">Daily Energy Pattern</div>
                            {% if charts.daily_energy %}
                            <img src="{{ charts.daily_energy }}" alt="Daily Energy Chart" />
                            {% else %}
                            <div class="muted">No daily series available.</div>
                            {% endif %}
                        </div>
                    </div>
                    <div class="chart-col">
                        <div class="chart-card">
                            <div class="chart-title">Device Consumption Share</div>
                            {% if charts.device_share %}
                            <img src="{{ charts.device_share }}" alt="Device Energy Share" />
                            {% else %}
                            <div class="muted">No device breakdown available.</div>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>

            {% if per_device %}
            <div class="section">
                <div class="section-kicker">Operational Detail</div>
                <div class="section-title-row">
                    <h2>Device Breakdown</h2>
                    <div class="section-subtitle">Per-device confidence and calculation method</div>
                </div>
                <p class="section-intro">Review device totals, peak demand, quality grading, and computation method to validate the result set before acting on anomalies.</p>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Device</th>
                                <th>Total kWh</th>
                                <th>Peak kW</th>
                                <th>Load Factor</th>
                                <th>Quality</th>
                                <th>Method</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for d in per_device %}
                            <tr>
                                <td>{{ d.device_name }}</td>
                                <td class="numeric">{{ d.total_kwh if d.total_kwh is not none else "N/A" }}</td>
                                <td class="numeric">{{ d.peak_demand_kw if d.peak_demand_kw is not none else "N/A" }}</td>
                                <td class="numeric">{{ d.load_factor_pct if d.load_factor_pct is not none else "N/A" }}</td>
                                <td>
                                    <span class="badge {% if d.quality == 'high' %}badge-good{% elif d.quality == 'medium' %}badge-medium{% elif d.quality == 'low' %}badge-low{% else %}badge-muted{% endif %}">
                                        {{ d.quality }}
                                    </span>
                                </td>
                                <td>{{ d.method }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            {% endif %}

            {% if daily_series %}
            <div class="section">
                <div class="section-kicker">Day-Level View</div>
                <div class="section-title-row">
                    <h2>Daily Energy Breakdown</h2>
                    <div class="section-subtitle">Aggregated by day across all devices</div>
                </div>
                <p class="section-intro">Daily totals help isolate abnormal demand days, energy spikes, and operational drift across the selected range.</p>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th class="right">Energy (kWh)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for day in daily_series %}
                            <tr>
                                <td>{{ day.date }}</td>
                                <td class="financial">{{ day.kwh }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
            {% endif %}

            {% if overtime_summary %}
            <div class="section">
                <div class="section-kicker">Schedule Exposure</div>
                <div class="section-title-row">
                    <h2>Overtime Breakdown</h2>
                    <div class="section-subtitle">Same as off-hours running: all running outside configured shift hours</div>
                </div>
                <p class="section-intro">Overtime is the same operational metric as off-hours running in waste analysis: all running energy outside approved shift windows for the selected period.</p>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Total Overtime</div>
                        <div class="kpi-value">{% if overtime_summary.total_minutes is not none %}{{ overtime_summary.total_minutes }} min{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if overtime_summary.total_hours is not none %}{{ overtime_summary.total_hours }} hours{% else %}Duration unavailable{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Overtime Energy</div>
                        <div class="kpi-value">{% if overtime_summary.total_kwh is not none %}{{ overtime_summary.total_kwh }} kWh{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">Energy consumed outside shift hours</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Overtime Cost</div>
                        <div class="kpi-value">{% if overtime_summary.total_cost is not none %}{{ overtime_summary.currency }} {{ overtime_summary.total_cost }}{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if overtime_summary.tariff_rate_used is not none %}{{ overtime_summary.currency }} {{ overtime_summary.tariff_rate_used }} / kWh{% else %}Tariff not configured{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Configured Devices</div>
                        <div class="kpi-value">{{ overtime_summary.configured_devices }} / {{ overtime_summary.device_count }}</div>
                        <div class="kpi-note">{% if overtime_summary.devices_without_shift > 0 %}{{ overtime_summary.devices_without_shift }} device(s) excluded{% else %}All devices had active shifts{% endif %}</div>
                    </div>
                </div>

                <div class="summary-strip">
                    <div class="summary-item"><strong>Shift Coverage</strong>{{ overtime_summary.configured_devices }} device{% if overtime_summary.configured_devices != 1 %}s{% endif %} configured</div>
                    <div class="summary-item"><strong>Charge Basis</strong>Outside configured shift hours</div>
                    <div class="summary-item"><strong>Tariff Snapshot</strong>{% if overtime_summary.tariff_rate_used is not none %}{{ overtime_summary.currency }} {{ overtime_summary.tariff_rate_used }} / kWh{% else %}Not configured{% endif %}</div>
                    <div class="summary-item"><strong>Overtime Cost</strong>{% if overtime_summary.total_cost is not none %}{{ overtime_summary.currency }} {{ overtime_summary.total_cost }}{% else %}N/A{% endif %}</div>
                </div>

                <div class="notice">Each overtime proof row below shows the exact outside-shift window in platform local time so teams can audit when running happened, not just how much was counted.</div>

                {% if overtime_summary.device_summary %}
                <div class="table-wrap overtime-table" style="margin-top: 10px;">
                    <table>
                        <thead>
                            <tr>
                                <th>Device</th>
                                <th>Shift Status</th>
                                <th class="align-right">Minutes</th>
                                <th class="align-right">Hours</th>
                                <th class="align-right">kWh</th>
                                <th class="align-right">Cost</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for item in overtime_summary.device_summary %}
                            <tr class="{% if item.configured %}zero-row{% else %}overtime-row{% endif %}">
                                <td>{{ item.device_name }}</td>
                                <td>
                                    <span class="badge {% if item.configured %}badge-success-soft{% else %}badge-danger{% endif %}">
                                        {% if item.configured %}Configured{% else %}Missing shift{% endif %}
                                    </span>
                                </td>
                                <td class="align-right">{{ item.total_overtime_minutes }}</td>
                                <td class="align-right">{{ item.total_overtime_hours }}</td>
                                <td class="align-right">{{ item.total_overtime_kwh }}</td>
                                <td class="financial">{% if item.total_overtime_cost is not none %}{{ item.currency }} {{ item.total_overtime_cost }}{% else %}N/A{% endif %}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% endif %}

                {% if overtime_summary.rows %}
                <div class="table-wrap overtime-table" style="margin-top: 10px;">
                    <table>
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Device</th>
                                <th>Shift Status</th>
                                <th>From</th>
                                <th>To</th>
                                <th class="align-right">Minutes</th>
                                <th class="align-right">Hours</th>
                                <th class="align-right">kWh</th>
                                <th class="align-right">Cost</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in overtime_summary.rows %}
                            <tr class="{% if row.overtime_minutes and row.overtime_minutes > 0 %}overtime-row{% else %}zero-row{% endif %}">
                                <td>{{ row.date }}</td>
                                <td>{{ row.device_name }}</td>
                                <td>
                                    <span class="badge {% if row.overtime_minutes and row.overtime_minutes > 0 %}badge-danger{% else %}badge-success-soft{% endif %}">
                                        {{ row.shift_status if row.shift_status else ("Overtime" if row.overtime_minutes and row.overtime_minutes > 0 else "Within shift") }}
                                    </span>
                                </td>
                                <td>{{ row.window_start if row.window_start else "N/A" }}</td>
                                <td>{{ row.window_end if row.window_end else "N/A" }}</td>
                                <td class="align-right">{{ row.overtime_minutes }}</td>
                                <td class="align-right">{{ row.overtime_hours }}</td>
                                <td class="align-right">{{ row.overtime_kwh }}</td>
                                <td class="financial">{% if row.overtime_cost is not none %}{{ overtime_summary.currency }} {{ row.overtime_cost }}{% else %}N/A{% endif %}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <div class="notice">No overtime was detected for the selected range.</div>
                {% endif %}

                {% if overtime_summary.devices_without_shift > 0 %}
                <div class="warning">{{ overtime_summary.devices_without_shift }} device(s) had no active shift configuration and were excluded from overtime charging.</div>
                {% endif %}
            </div>
            {% endif %}

            <div class="section">
                <div class="section-kicker">Commercial Context</div>
                <div class="section-title-row">
                    <h2>Cost and Data Notes</h2>
                    <div class="section-subtitle">Tariff snapshot and calculation context</div>
                </div>
                <p class="section-intro">These notes capture tariff assumptions, telemetry gaps, and any warning signals that materially affect interpretation of the report.</p>
                {% if tariff_rate_used is not none %}
                <div class="notice">Tariff fetched at {{ tariff_fetched_at }} using {{ currency }} {{ tariff_rate_used }} per kWh. Estimated total cost: {{ currency }} {{ total_cost }}.</div>
                {% else %}
                <div class="error">Tariff not configured. Cost calculation was skipped for this report.</div>
                {% endif %}
                {% if warnings %}
                {% for warning in warnings %}
                <div class="warning">{{ warning }}</div>
                {% endfor %}
                {% endif %}
            </div>

            {% if insights %}
            <div class="section">
                <div class="section-kicker">Decision Support</div>
                <div class="section-title-row">
                    <h2>Key Insights</h2>
                    <div class="section-subtitle">Highlights for quick review</div>
                </div>
                <p class="section-intro">Use these prioritized observations to guide investigations, follow-up reviews, and operational actions.</p>
                <ul class="insight-list">
                    {% for insight in insights %}
                    <li>{{ loop.index }}. {{ insight }}</li>
                    {% endfor %}
                </ul>
            </div>
            {% endif %}

            <div class="footer">
                <strong>Shivex</strong> professional energy report generated for {{ device_label }}.
            </div>
        </div>
    </div>
</body>
</html>
"""


def get_comparison_report_template():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Energy Comparison Report</title>
    """ + _report_styles() + """
</head>
<body class="{{ report_theme_class }}">
    <div class="page">
        <div class="hero">
            <div class="hero-topbar">
                <div class="hero-brand">
                    <div class="brand-kicker">Shivex Energy Intelligence</div>
                    <div class="brand-name">Comparison Report</div>
                </div>
                <div class="hero-stamp">
                    <div>
                        <div class="stamp-label">Generated</div>
                        <div class="stamp-value">{{ generated_at }}</div>
                    </div>
                </div>
            </div>
            <h1>Energy Comparison Report</h1>
            <div class="hero-subtitle">
                A decision-ready comparison of energy usage, demand, and efficiency outcomes across two devices in the same reporting window.
            </div>
            <div class="hero-caption">Comparing: {{ device_a_name }} vs {{ device_b_name }} | Period: {{ start_date }} to {{ end_date }}</div>
            <div class="hero-meta">
                <div class="meta-chip"><div><span class="meta-label">Report ID</span><span class="meta-value">{{ report_id }}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Winner</span><span class="meta-value">{% if winner %}{{ winner }}{% else %}Pending{% endif %}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Scope</span><span class="meta-value">{{ device_a_name }} vs {{ device_b_name }}</span></div></div>
                <div class="meta-chip"><div><span class="meta-label">Insight Count</span><span class="meta-value">{{ insights|length }}</span></div></div>
            </div>
        </div>

        <div class="content">
            <div class="section">
                <div class="section-kicker">Executive Overview</div>
                <div class="section-title-row">
                    <h2>Executive Summary</h2>
                    <div class="section-subtitle">High-level comparison at a glance</div>
                </div>
                <p class="section-intro">This summary highlights the spread between the two devices and frames the operational decision with the clearest top-line metrics first.</p>
                <div class="kpi-grid">
                    <div class="kpi-card">
                        <div class="kpi-label">Energy Difference</div>
                        <div class="kpi-value">{% if comparison.energy_comparison %}{{ comparison.energy_comparison.difference_kwh }} kWh{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if comparison.energy_comparison %}{{ comparison.energy_comparison.difference_percent }}% spread{% else %}Energy comparison unavailable{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Demand Difference</div>
                        <div class="kpi-value">{% if comparison.demand_comparison %}{{ comparison.demand_comparison.difference_kw }} kW{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">{% if comparison.demand_comparison %}{{ comparison.demand_comparison.difference_percent }}% spread{% else %}Demand comparison unavailable{% endif %}</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">Higher Consumer</div>
                        <div class="kpi-value">{% if comparison.energy_comparison %}{{ comparison.energy_comparison.higher_consumer }}{% else %}N/A{% endif %}</div>
                        <div class="kpi-note">Based on total energy usage</div>
                    </div>
                    <div class="kpi-card">
                        <div class="kpi-label">More Efficient</div>
                        <div class="kpi-value">{% if winner %}{{ winner }}{% else %}Pending{% endif %}</div>
                        <div class="kpi-note">Current analysis outcome</div>
                    </div>
                </div>

                <div class="two-col" style="margin-top: 10px;">
                    <div class="two-col-cell">
                        <div class="spotlight-card">
                            <div class="spotlight-label">Recommended Winner</div>
                            <div class="spotlight-value">{% if winner %}{{ winner }}{% else %}Pending{% endif %}</div>
                            <div class="spotlight-note">Selected from the current analysis based on the available comparison metrics.</div>
                        </div>
                    </div>
                    <div class="two-col-cell">
                        <div class="callout-card">
                            <h3>How To Use This Comparison</h3>
                            <p>Read the summary cards first, then validate the chart and numeric tables to confirm whether the decision aligns with your operational context.</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="section">
                <div class="section-kicker">Visual Comparison</div>
                <div class="section-title-row">
                    <h2>Comparison Chart</h2>
                    <div class="section-subtitle">Visual summary of the metrics used</div>
                </div>
                <p class="section-intro">The visual comparison makes it easy to spot which device is carrying more energy or demand load without scanning the tables first.</p>
                <div class="chart-card">
                    <div class="chart-title">Comparison Overview</div>
                    {% if comparison_chart %}
                    <img src="{{ comparison_chart }}" alt="Comparison chart" />
                    {% else %}
                    <div class="muted">No comparison chart available.</div>
                    {% endif %}
                </div>
            </div>

            <div class="section">
                <div class="section-kicker">Numeric Detail</div>
                <div class="section-title-row">
                    <h2>Energy and Demand Details</h2>
                    <div class="section-subtitle">Device-by-device numeric breakdown</div>
                </div>
                <p class="section-intro">These tables preserve the raw comparison values behind the headline call so reviewers can verify the final recommendation.</p>
                <div class="chart-row">
                    <div class="chart-col">
                        <div class="table-wrap">
                            <table>
                                <thead><tr><th>Energy Comparison</th><th class="align-right">kWh</th></tr></thead>
                                <tbody>
                                    <tr><td>{{ device_a_name }}</td><td class="financial">{% if comparison.energy_comparison %}{{ comparison.energy_comparison.device_a_kwh }}{% else %}N/A{% endif %}</td></tr>
                                    <tr><td>{{ device_b_name }}</td><td class="financial">{% if comparison.energy_comparison %}{{ comparison.energy_comparison.device_b_kwh }}{% else %}N/A{% endif %}</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div class="chart-col">
                        <div class="table-wrap">
                            <table>
                                <thead><tr><th>Demand Comparison</th><th class="align-right">kW</th></tr></thead>
                                <tbody>
                                    <tr><td>{{ device_a_name }}</td><td class="financial">{% if comparison.demand_comparison %}{{ comparison.demand_comparison.device_a_peak_kw }}{% else %}N/A{% endif %}</td></tr>
                                    <tr><td>{{ device_b_name }}</td><td class="financial">{% if comparison.demand_comparison %}{{ comparison.demand_comparison.device_b_peak_kw }}{% else %}N/A{% endif %}</td></tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {% if comparison.energy_comparison %}
                <div class="notice">Energy difference: {{ comparison.energy_comparison.difference_kwh }} kWh ({{ comparison.energy_comparison.difference_percent }}%). Higher consumer: {{ comparison.energy_comparison.higher_consumer }}.</div>
                {% endif %}
                {% if comparison.demand_comparison %}
                <div class="notice">Demand difference: {{ comparison.demand_comparison.difference_kw }} kW ({{ comparison.demand_comparison.difference_percent }}%). Higher demand: {{ comparison.demand_comparison.higher_demand }}.</div>
                {% endif %}
            </div>

            {% if insights %}
            <div class="section">
                <div class="section-kicker">Decision Support</div>
                <div class="section-title-row">
                    <h2>Key Insights</h2>
                    <div class="section-subtitle">Interpretive takeaways for the reader</div>
                </div>
                <p class="section-intro">These insights summarize the comparison in human terms so reviewers can quickly align on the operational takeaway.</p>
                <ul class="insight-list">
                    {% for insight in insights %}
                    <li>{{ loop.index }}. {{ insight }}</li>
                    {% endfor %}
                </ul>
            </div>
            {% endif %}

            {% if winner %}
            <div class="section">
                <div class="section-kicker">Decision Summary</div>
                <div class="section-title-row">
                    <h2>Winner</h2>
                    <div class="section-subtitle">Decision summary</div>
                </div>
                <div class="notice"><strong>{{ winner }}</strong> is the more efficient choice based on the analysis.</div>
            </div>
            {% endif %}

            <div class="footer">
                <strong>Shivex</strong> professional comparison report for {{ device_a_name }} and {{ device_b_name }}.
            </div>
        </div>
    </div>
</body>
</html>
"""


pdf_builder = type(
    "PDFBuilder",
    (),
    {
        "generate_consumption_pdf": staticmethod(generate_consumption_pdf),
        "generate_comparison_pdf": staticmethod(generate_comparison_pdf),
    },
)()
