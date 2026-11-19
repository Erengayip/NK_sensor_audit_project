"""Streamlit-интерфейс аудита сенсоров."""

import sqlite3
from contextlib import closing
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from etl import DB, RESULTS, SPLIT

WELL_TYPES = {"fountain": "Фонтанная", "sucker_rod_pump": "Штанговый насос"}


@st.cache_data
def sql_frame(revision, sql, params=()):
    with closing(sqlite3.connect(DB)) as con:
        return pd.read_sql_query(sql, con, params=params)


def sensor_chart(hours, parameter, unit):
    fig = go.Figure()
    fig.add_scatter(
        x=hours["timestamp"], y=hours["value"], name=parameter, mode="lines",
        line={"color": "#087F80", "width": 1.7}, connectgaps=False,
        customdata=hours[["n_obs", "split"]],
        hovertemplate="%{x|%d.%m.%Y %H:%M}<br>%{y:.4g} " + unit +
                      "<br>Исходных записей: %{customdata[0]}<br>%{customdata[1]}<extra></extra>",
    )
    flagged = hours.loc[hours["flag"].notna()]
    if not flagged.empty:
        fig.add_scatter(
            x=flagged["timestamp"], y=flagged["value"], mode="markers", name="Есть флаг",
            marker={"color": "#BD5B37", "size": 6}, customdata=flagged["flag"],
            hovertemplate="%{x|%d.%m.%Y %H:%M}<br>%{y:.4g}<br>%{customdata}<extra></extra>",
        )
    if hours["timestamp"].min() < SPLIT <= hours["timestamp"].max():
        fig.add_vline(x=SPLIT.to_pydatetime(), line_dash="dot", line_color="#667788")
    fig.update_layout(
        height=465, margin={"l": 16, "r": 16, "t": 14, "b": 16}, yaxis_title=unit,
        xaxis={"rangeslider": {"visible": True, "thickness": 0.12}},
        legend={"orientation": "h", "y": 1.06}, hovermode="closest",
    )
    return fig


def main():
    st.set_page_config(page_title="Аудит сенсоров NK", layout="wide")
    st.title("Аудит сенсоров NK")
    if not DB.exists():
        st.error("База данных ещё не создана. Выполните python run.py и обновите страницу.")
        st.stop()
    revision = DB.stat().st_mtime_ns
    sensors = sql_frame(revision, "SELECT * FROM sensors JOIN wells USING (well_id) ORDER BY well_id, parameter")
    bounds = sql_frame(revision, "SELECT MIN(timestamp) AS start, MAX(timestamp) AS end FROM hourly_wide")
    first = pd.Timestamp(bounds.at[0, "start"]).date()
    last = pd.Timestamp(bounds.at[0, "end"]).date()
    filters = st.columns([1, 1.4, 2])
    options = sensors["well_id"].unique().tolist()
    well = filters[0].selectbox("Скважина", options, index=options.index("NK-7"))
    selected = sensors.loc[sensors["well_id"].eq(well)].set_index("parameter")
    parameter = filters[1].selectbox("Параметр", selected.index.tolist())
    dates = filters[2].date_input("Период", (first, last), min_value=first, max_value=last,
                                  format="DD.MM.YYYY")
    if len(dates) != 2:
        st.info("Выберите дату окончания периода.")
        st.stop()
    start, end = dates
    data = sql_frame(
        revision,
        """SELECT w.timestamp, w.split, o.value, o.n_obs, o.flag
           FROM hourly_wide AS w LEFT JOIN observations AS o
           ON o.well_id = w.well_id AND o.timestamp = w.timestamp AND o.parameter = ?
           WHERE w.well_id = ? AND w.timestamp >= ? AND w.timestamp < ?
           ORDER BY w.timestamp""",
        (parameter, well, start.isoformat(), (end + timedelta(days=1)).isoformat()),
    )
    data["timestamp"] = pd.to_datetime(data["timestamp"])
    unit = selected.at[parameter, "unit"]
    st.caption(f"{WELL_TYPES[selected.at[parameter, 'well_type']]} · {well} · {unit}")
    missing = int(data["value"].isna().sum())
    metrics = st.columns(4)
    metrics[0].metric("Часов в периоде", f"{len(data):,}".replace(",", " "))
    metrics[1].metric("Часов с измерением", f"{len(data) - missing:,}".replace(",", " "))
    metrics[2].metric("Часов без значения", f"{missing:,}".replace(",", " "))
    metrics[3].metric("Часов с флагом", int(data["flag"].notna().sum()))
    tab_series, tab_audit = st.tabs(["Временной ряд", "Сводки аудита"])
    with tab_series:
        if missing == len(data):
            st.info("В выбранном периоде у параметра отсутствуют измерения.")
        st.plotly_chart(sensor_chart(data, parameter, unit), width="stretch",
                        config={"displaylogo": False, "scrollZoom": True})
        st.caption("Разрывы линии показывают часы без значения. Пунктир отмечает начало test, если граница попадает в период.")
        st.download_button("Скачать выбранные часы в CSV", data.to_csv(index=False).encode("utf-8-sig"),
                           f"{well}_{parameter}.csv", "text/csv")
    with tab_audit:
        st.caption("Сводки по всем скважинам и всему периоду.")
        tables = {
            "Покрытие по датчикам": "coverage",
            "Флаги по отдельным признакам": "flag_tokens",
            "Совпадение ключей и значений v1 и v2": "version_comparison",
            "Сравнение методов поиска пропусков": "method_comparison",
        }
        for label, name in tables.items():
            with st.expander(label):
                st.dataframe(pd.read_csv(RESULTS / f"{name}.csv"), hide_index=True)


if __name__ == "__main__":
    main()
