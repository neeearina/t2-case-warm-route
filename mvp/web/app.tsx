import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./style.css";

type Status = "VERIFYING" | "ACTIVE" | "RESOLVED" | "RECHECK" | "CLOSED";
type Segment = {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  kind: string;
};
type Signal = {
  id: number;
  text: string;
  source: string;
  synthetic: boolean;
  occurred_at: string;
};
type Incident = {
  id: number;
  segment_id: number;
  category: string;
  status: Status;
  score: number;
  started_at: string;
  recheck_at: string | null;
  explanation: {
    factors?: Record<string, number>;
    contributions?: Record<string, number>;
    missing_or_stale?: string[];
    evaluated_at?: string;
    synthetic_signals?: boolean;
    sources?: { source: string; synthetic: boolean }[];
    score_before_close?: number;
  };
  signals?: Signal[];
  history?: { status: Status; changed_at: string; reason: string }[];
};
type Source = {
  source: string;
  last_success: string | null;
  last_error: string | null;
  stale: boolean;
};
const statuses: Record<Status, string> = {
  VERIFYING: "На проверке",
  ACTIVE: "Активна",
  RESOLVED: "Устранена",
  RECHECK: "Повторная проверка",
  CLOSED: "Закрыта",
};
const categories: Record<string, string> = {
  ice: "Гололёд",
  snow: "Неубранный снег",
  delay: "Задержка транспорта",
};
const sourceNames: Record<string, string> = {
  weather: "Погода",
  mobility: "Мобильность",
  transport: "Транспорт",
  reports: "Обращения",
  manual: "Диспетчер",
};
const factorNames: Record<string, string> = {
  hazard: "Опасность",
  mobility: "Поток людей",
  criticality: "Значимость участка",
  duration: "Длительность",
  confidence: "Достоверность",
};
const actions: Record<Status, [Status, string][]> = {
  VERIFYING: [["ACTIVE", "Подтвердить проблему"]],
  ACTIVE: [["RESOLVED", "Отметить устранение"]],
  RESOLVED: [
    ["RECHECK", "Проверить сейчас"],
    ["ACTIVE", "Проблема сохраняется"],
  ],
  RECHECK: [
    ["CLOSED", "Подтвердить закрытие"],
    ["ACTIVE", "Проблема сохраняется"],
  ],
  CLOSED: [],
};
const time = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString("ru-RU", {
        timeZone: "Asia/Yekaterinburg",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Ещё нет данных";
const priority = (score: number) =>
  score >= 70 ? "high" : score >= 40 ? "medium" : "low";
const color = (score: number) =>
  score >= 70 ? "#e36345" : score >= 40 ? "#c18a24" : "#49957e";
async function api<T>(
  path: string,
  body?: unknown,
  method = "GET",
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      response.status === 409
        ? "Состояние изменилось или действие недоступно. Обновите данные."
        : typeof data?.detail === "string"
          ? data.detail
          : `Не удалось выполнить запрос (${response.status})`,
    );
  }
  return response.json();
}
async function loadIncidents() {
  const all: Incident[] = [];
  for (let offset = 0; ; offset += 100) {
    const { items } = await api<{ items: Incident[] }>(
      `/incidents?limit=100&offset=${offset}`,
    );
    all.push(...items);
    if (items.length < 100) return all;
  }
}
function MapView({
  segments,
  incidents,
  selected,
  onSelect,
}: {
  segments: Segment[];
  incidents: Incident[];
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const el = useRef<HTMLDivElement>(null),
    map = useRef<L.Map | null>(null),
    markers = useRef<L.LayerGroup | null>(null);
  const bounds = useRef<L.LatLngBounds | null>(null),
    fitted = useRef(false);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    if (!el.current) return;
    const m = L.map(el.current, { zoomControl: false }).setView(
      [57.152, 65.548],
      14,
    );
    map.current = m;
    L.control.zoom({ position: "bottomright" }).addTo(m);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    })
      .on("tileerror", () => setUnavailable(true))
      .addTo(m);
    markers.current = L.layerGroup().addTo(m);
    const observer = new ResizeObserver(() => {
      m.invalidateSize();
      if (bounds.current)
        m.fitBounds(bounds.current, {
          paddingTopLeft: [45, 115],
          paddingBottomRight: [45, 65],
          maxZoom: 14,
          animate: false,
        });
    });
    observer.observe(el.current);
    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    if (!markers.current) return;
    markers.current.clearLayers();
    if (segments.length) {
      bounds.current = L.latLngBounds(
        segments.map((s) => [s.latitude, s.longitude] as [number, number]),
      );
      if (!fitted.current) {
        map.current?.fitBounds(bounds.current, {
          paddingTopLeft: [45, 115],
          paddingBottomRight: [45, 65],
          maxZoom: 14,
          animate: false,
        });
        fitted.current = true;
      }
    }
    segments.forEach((segment) => {
      const related = incidents.filter(
        (i) => i.segment_id === segment.id && i.status !== "CLOSED",
      );
      const chosen = related.find((i) => i.id === selected) || related[0];
      const active = chosen?.id === selected;
      const marker = L.marker([segment.latitude, segment.longitude], {
        icon: L.divIcon({
          className: "map-marker",
          html: `<span style="--pin:${chosen ? color(chosen.score) : "#778681"}" class="${active ? "selected" : ""}">${chosen ? Math.round(chosen.score) : "·"}</span>`,
          iconSize: [42, 42],
          iconAnchor: [21, 21],
        }),
        keyboard: true,
        title: segment.name,
      }).addTo(markers.current!);
      const text = document.createElement("span");
      text.textContent = segment.name;
      marker.bindTooltip(text);
      marker.on("click", () => {
        if (chosen) onSelect(chosen.id);
      });
    });
  }, [segments, incidents, selected, onSelect]);
  return (
    <div className="map-wrap">
      <div
        ref={el}
        className="map"
        aria-label="Карта демонстрационных участков Тюмени"
      />
      <div className="map-tag">
        <span className="pulse" /> Тюмень{" "}
        <small>{segments.length} демо-участков</small>
      </div>
      {unavailable && (
        <div className="tile-warning">
          Подложка карты недоступна. Точки участков остаются доступны.
        </div>
      )}
      <div className="legend">
        <span>
          <i style={{ background: "#e36345" }} />
          Высокий
        </span>
        <span>
          <i style={{ background: "#c18a24" }} />
          Средний
        </span>
        <span>
          <i style={{ background: "#49957e" }} />
          Низкий приоритет
        </span>
      </div>
    </div>
  );
}
function App() {
  const [segments, setSegments] = useState<Segment[]>([]),
    [incidents, setIncidents] = useState<Incident[]>([]),
    [sources, setSources] = useState<Source[]>([]);
  const [selected, setSelected] = useState<number | null>(null),
    [detail, setDetail] = useState<Incident | null>(null),
    [filter, setFilter] = useState("open");
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [updated, setUpdated] = useState<string | null>(null);
  const [modal, setModal] = useState<"report" | Status | null>(null),
    [busy, setBusy] = useState(false),
    [formError, setFormError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null),
    inflight = useRef(false),
    pendingRefresh = useRef(false),
    selection = useRef<number | null>(null),
    detailVersion = useRef(0);
  const submission = useRef<{
    key: string;
    body: Record<string, unknown>;
  } | null>(null);
  const select = useCallback((id: number) => {
    selection.current = id;
    setSelected(id);
    setDetail(null);
  }, []);
  const refresh = useCallback(async (): Promise<void> => {
    if (inflight.current) {
      pendingRefresh.current = true;
      return;
    }
    inflight.current = true;
    try {
      const [s, i, r] = await Promise.all([
        api<{ items: Segment[] }>("/segments"),
        loadIncidents(),
        api<{ items: Source[] }>("/sources"),
      ]);
      setSegments(s.items);
      setIncidents(i);
      setSources(r.items);
      setUpdated(new Date().toISOString());
      setError("");
      if (selection.current === null && i.length)
        select(i.find((row) => row.status !== "CLOSED")?.id ?? i[0].id);
      if (selection.current !== null) {
        const id = selection.current;
        const version = ++detailVersion.current;
        const next = await api<Incident>(`/incidents/${id}`);
        if (selection.current === id && version === detailVersion.current)
          setDetail(next);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Нет связи с сервером");
    } finally {
      setLoading(false);
      inflight.current = false;
      if (pendingRefresh.current) {
        pendingRefresh.current = false;
        queueMicrotask(() => void refresh());
      }
    }
  }, [select]);
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (selected === null) return;
    let active = true;
    const version = ++detailVersion.current;
    api<Incident>(`/incidents/${selected}`)
      .then((row) => {
        if (active && version === detailVersion.current) setDetail(row);
      })
      .catch(() => {
        if (active) setError("Не удалось загрузить карточку проблемы");
      });
    return () => {
      active = false;
    };
  }, [selected]);
  useEffect(() => {
    if (modal) {
      dialog.current?.showModal();
    } else dialog.current?.close();
  }, [modal]);
  function openModal(value: "report" | Status) {
    setFormError("");
    submission.current = null;
    setModal(value);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    const form = new FormData(event.currentTarget);
    try {
      if (modal === "report") {
        const segment = segments.find(
          (s) => s.id === Number(form.get("segment")),
        );
        if (!segment) throw new Error("Выберите участок");
        const fields = {
          latitude: segment.latitude,
          longitude: segment.longitude,
          category: form.get("category"),
          text: String(form.get("text")).trim(),
          synthetic: true,
        };
        const key = JSON.stringify(fields);
        if (submission.current?.key !== key)
          submission.current = {
            key,
            body: {
              ...fields,
              external_id: crypto.randomUUID(),
              occurred_at: new Date().toISOString(),
            },
          };
        const result = await api<{ incident_id: number | null }>(
          "/reports",
          submission.current.body,
          "POST",
        );
        if (result.incident_id) select(result.incident_id);
        setNotice("Обращение принято. Приоритет пересчитан.");
        setFilter("open");
      } else {
        await api(
          `/incidents/${selected}/status`,
          { status: modal, reason: String(form.get("reason")).trim() },
          "PATCH",
        );
        setNotice("Статус проблемы обновлён.");
      }
      setModal(null);
      await refresh();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Не удалось сохранить");
    } finally {
      setBusy(false);
    }
  }
  const visible = incidents.filter(
    (i) =>
      filter === "all" ||
      (filter === "open" && i.status !== "CLOSED") ||
      i.status === filter,
  );
  const open = incidents.filter((i) => i.status !== "CLOSED");
  const critical = open.filter((i) => i.score >= 70).length;
  const segmentFor = (id: number) =>
    segments.find((s) => s.id === id)?.name || `Участок ${id}`;
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <img
            src="/assets/brand/mark.svg"
            alt="Тёплый маршрут"
            width="42"
            height="42"
          />
        </div>
        <div className="rail-line" />
        <a className="rail-active" href="#main" aria-label="Обзор города">
          ▦
        </a>
        <span className="rail-caption">ТЁПЛЫЙ МАРШРУТ</span>
        <span className="rail-bottom">72</span>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <b>Тёплый маршрут</b>
            <span className="divider">/</span>
            <span>Панель диспетчера</span>
          </div>
          <span className="city">
            ↗ Тюмень <i /> UTC+5
          </span>
        </header>
        <main id="main">
          <section className="heading">
            <svg
              className="hero-route"
              viewBox="0 0 600 260"
              aria-hidden="true"
            >
              <g fill="none" stroke="#364138" strokeWidth="1">
                <path d="M0 50H600M0 160H600M110 0V260M330 0V260M530 0V260" />
              </g>
              <path
                d="M20 50H220Q260 50 260 90V130Q260 170 300 170H480Q530 170 530 220V260"
                fill="none"
                stroke="#C5F36B"
                strokeWidth="9"
                strokeLinecap="round"
              />
              <circle cx="130" cy="50" r="10" fill="#F5F6F3" />
              <circle cx="400" cy="170" r="14" fill="#E36345" />
              <circle cx="400" cy="170" r="32" fill="none" stroke="#E36345" />
              <circle
                cx="400"
                cy="170"
                r="48"
                fill="none"
                stroke="#E36345"
                opacity=".5"
              />
            </svg>
            <div>
              <div className="eyebrow">
                ГОРОДСКАЯ МОБИЛЬНОСТЬ · ЗИМНИЙ СЕЗОН
              </div>
              <h1>
                Город под наблюдением<span>.</span>
              </h1>
              <p>От сигнала — к приоритету.</p>
            </div>
            <button
              className="primary add"
              onClick={() => openModal("report")}
              disabled={!segments.length}
            >
              ＋ Добавить обращение
            </button>
          </section>
          <div className="demo-note">
            <span>ДЕМО</span> Синтетические потоки и обращения · условные
            участки Тюмени{" "}
            <span className="live">
              <i className="dot" /> Обновление каждые 10 сек.
            </span>
          </div>
          {error && (
            <div className="alert" role="alert">
              {error}. Последние загруженные данные могут быть неактуальны.{" "}
              <button onClick={() => void refresh()}>Повторить</button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
              <button
                aria-label="Скрыть уведомление"
                onClick={() => setNotice("")}
              >
                ×
              </button>
            </div>
          )}
          <section className="metrics" aria-label="Сводка">
            <div>
              <span>Открытых проблем</span>
              <strong>
                {loading ? "—" : open.length.toString().padStart(2, "0")}
              </strong>
              <small>в работе и на проверке</small>
            </div>
            <div>
              <span>
                Высокий приоритет <i className="dot hot" />
              </span>
              <strong>
                {loading ? "—" : critical.toString().padStart(2, "0")}
              </strong>
              <small>Impact Score от 70</small>
            </div>
            <div>
              <span>Ожидают проверки</span>
              <strong>
                {loading
                  ? "—"
                  : open
                      .filter((i) =>
                        ["VERIFYING", "RECHECK"].includes(i.status),
                      )
                      .length.toString()
                      .padStart(2, "0")}
              </strong>
              <small>нужно решение диспетчера</small>
            </div>
            <div className="metric-status">
              <span>
                <i className={`dot ${error ? "hot" : ""}`} /> Состояние данных
              </span>
              <b>
                {loading
                  ? "Подключаемся…"
                  : error
                    ? "Нет связи"
                    : sources.some((s) => s.stale || s.last_error)
                      ? "Есть задержки"
                      : "Данные обновлены"}
              </b>
              <small>{time(updated)}</small>
            </div>
          </section>
          <div className="dashboard">
            <section className="overview">
              <div className="section-title">
                <h2>Карта приоритетов</h2>
                <span>01 / ОБЗОР</span>
              </div>
              <MapView
                segments={segments}
                incidents={incidents}
                selected={selected}
                onSelect={select}
              />
              <div className="section-title list-title">
                <h2>
                  Проблемные участки{" "}
                  <span className="count">{visible.length}</span>
                </h2>
                <select
                  aria-label="Фильтр статуса"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="open">Все открытые</option>
                  {Object.entries(statuses).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                  <option value="all">Вся история</option>
                </select>
              </div>
              <div className="incident-list">
                {loading ? (
                  <div className="empty">Загружаем городские данные…</div>
                ) : visible.length === 0 ? (
                  <div className="empty">
                    В этой категории пока нет проблем.
                    <br />
                    <small>
                      Выберите другой статус или добавьте обращение.
                    </small>
                  </div>
                ) : (
                  visible.map((item, index) => (
                    <button
                      className={`incident-row ${selected === item.id ? "chosen" : ""}`}
                      key={item.id}
                      onClick={() => select(item.id)}
                    >
                      <span className="rank">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="row-text">
                        <strong>{categories[item.category]}</strong>
                        <small>{segmentFor(item.segment_id)}</small>
                      </span>
                      <span className={`badge ${item.status.toLowerCase()}`}>
                        {statuses[item.status]}
                      </span>
                      <span className={`score ${priority(item.score)}`}>
                        {Math.round(item.score)}
                        <small>IMPACT</small>
                      </span>
                      <span className="arrow">↗</span>
                    </button>
                  ))
                )}
              </div>
            </section>
            <aside className="detail">
              <div className="section-title">
                <h2>Карточка проблемы</h2>
                <span>02 / ДЕТАЛИ</span>
              </div>
              {!detail ? (
                <div className="detail-empty">
                  {selected
                    ? "Загружаем карточку…"
                    : "Выберите проблему на карте или в списке."}
                </div>
              ) : (
                <div className="detail-card" key={detail.id}>
                  <div className="detail-top">
                    <span className={`badge ${detail.status.toLowerCase()}`}>
                      {statuses[detail.status]}
                    </span>
                    <span className="mono">
                      № {String(detail.id).padStart(4, "0")}
                    </span>
                  </div>
                  <h2>{categories[detail.category]}</h2>
                  <p className="location">⌖ {segmentFor(detail.segment_id)}</p>
                  <div className={`impact-box ${priority(detail.score)}`}>
                    <div>
                      <span>IMPACT SCORE</span>
                      <strong>
                        {Math.round(detail.score)}
                        <small>/ 100</small>
                      </strong>
                    </div>
                    <div className="impact-label">
                      {detail.status === "CLOSED"
                        ? "Проблема закрыта"
                        : detail.score >= 70
                          ? "Высокий приоритет"
                          : detail.score >= 40
                            ? "Средний приоритет"
                            : "Низкий приоритет"}
                      <small>
                        {detail.status === "CLOSED"
                          ? "Проверка подтверждена"
                          : "Оценка для принятия решения"}
                      </small>
                    </div>
                  </div>
                  <h3>
                    {detail.status === "CLOSED"
                      ? "Факторы перед закрытием"
                      : "Из чего складывается оценка"}
                  </h3>
                  <div className="factors">
                    {Object.entries(detail.explanation.contributions || {}).map(
                      ([key, value]) => (
                        <div className="factor" key={key}>
                          <div>
                            <span>{factorNames[key] || key}</span>
                            <b>+{value.toFixed(1)}</b>
                          </div>
                          <div className="track">
                            <i
                              style={{
                                width: `${Math.min(100, (value / 35) * 100)}%`,
                              }}
                            />
                          </div>
                        </div>
                      ),
                    )}
                  </div>
                  {!!detail.explanation.missing_or_stale?.length && (
                    <p className="quality">
                      Недостаточно свежих данных:{" "}
                      {detail.explanation.missing_or_stale
                        .map((s) => sourceNames[s])
                        .join(", ")}
                      . Использованы средние значения.
                    </p>
                  )}
                  <div className="provenance">
                    {detail.explanation.synthetic_signals
                      ? "Сигналы содержат демонстрационные данные."
                      : "Сигналы введены диспетчером."}{" "}
                    {detail.explanation.sources?.some(
                      (s) => s.source === "weather" && !s.synthetic,
                    ) && (
                      <a
                        href="https://open-meteo.com/"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Модельная погода: Open-Meteo ↗
                      </a>
                    )}
                  </div>
                  <div className="actions">
                    {actions[detail.status].map(([next, label], index) => (
                      <button
                        key={next}
                        className={index === 0 ? "primary" : "secondary"}
                        onClick={() => openModal(next)}
                      >
                        {label} <span>↗</span>
                      </button>
                    ))}
                  </div>
                  {detail.status === "RESOLVED" && (
                    <p className="hint">
                      Автоматическая повторная проверка:{" "}
                      {time(detail.recheck_at)}. Можно начать её сейчас.
                    </p>
                  )}
                  {detail.status === "RECHECK" && (
                    <p className="hint">
                      Подтвердите устранение после проверки участка. Отсутствие
                      новых обращений не означает, что проблема решена.
                    </p>
                  )}
                  <details className="evidence" open>
                    <summary>
                      Подтверждающие сигналы{" "}
                      <span>{detail.signals?.length || 0}</span>
                    </summary>
                    {detail.signals?.map((signal) => (
                      <div className="evidence-item" key={signal.id}>
                        <p>{signal.text}</p>
                        <small>
                          {sourceNames[signal.source] || signal.source} ·{" "}
                          {time(signal.occurred_at)}
                          {signal.synthetic ? " · демо" : ""}
                        </small>
                      </div>
                    ))}
                  </details>
                  <details className="history">
                    <summary>История изменений</summary>
                    {detail.history?.map((row, index) => (
                      <div className="history-item" key={index}>
                        <b>{statuses[row.status]}</b>
                        <small>{time(row.changed_at)}</small>
                        <p>{row.reason}</p>
                      </div>
                    ))}
                  </details>
                  <div className="updated">
                    Оценка: {time(detail.explanation.evaluated_at)}
                  </div>
                </div>
              )}
            </aside>
          </div>
          <section className="source-section">
            <div className="section-title">
              <h2>Источники данных</h2>
              <span>03 / СИНХРОНИЗАЦИЯ</span>
            </div>
            <div className="source-grid">
              {sources.map((source) => (
                <div className="source" key={source.source}>
                  <i
                    className={`dot ${source.stale || source.last_error ? "hot" : ""}`}
                  />
                  <div>
                    <strong>{sourceNames[source.source]}</strong>
                    <small>
                      {source.last_error
                        ? "Ошибка загрузки"
                        : source.stale
                          ? "Данные устарели"
                          : "Доступен"}{" "}
                      · {time(source.last_success)}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </section>
          <footer>
            <span>
              <img
                src="/assets/brand/mark-dark.svg"
                alt=""
                width="24"
                height="24"
              />{" "}
              Тёплый маршрут
            </span>
            <span>Прототип поддержки городских решений · Тюмень</span>
            <a href="/docs" target="_blank">
              API ↗
            </a>
          </footer>
        </main>
      </div>
      <dialog
        ref={dialog}
        onCancel={(e) => {
          if (busy) e.preventDefault();
          else setModal(null);
        }}
      >
        <form onSubmit={submit} key={`${modal}-${selected}`}>
          <div className="modal-heading">
            <span className="eyebrow">
              {modal === "report" ? "НОВЫЙ СИГНАЛ" : "ДЕЙСТВИЕ ДИСПЕТЧЕРА"}
            </span>
            <button
              type="button"
              aria-label="Закрыть форму"
              disabled={busy}
              onClick={() => setModal(null)}
            >
              ×
            </button>
          </div>
          <h2>
            {modal === "report"
              ? "Добавить обращение"
              : modal
                ? statuses[modal]
                : ""}
          </h2>
          {modal === "report" ? (
            <>
              <p>
                Сигнал будет привязан к выбранному участку и учтён в оценке.
              </p>
              <label>
                Участок
                <select name="segment" required>
                  {segments.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Тип проблемы
                <select name="category">
                  {Object.entries(categories).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Описание
                <textarea
                  name="text"
                  required
                  minLength={3}
                  maxLength={2000}
                  placeholder="Что произошло на участке?"
                />
              </label>
              <p className="hint">
                Обращение будет отмечено как демонстрационное.
              </p>
            </>
          ) : (
            <>
              <p>
                Инцидент № {selected}. Укажите основание для изменения статуса.
              </p>
              <label>
                Результат проверки
                <textarea
                  name="reason"
                  required
                  minLength={3}
                  maxLength={500}
                  placeholder="Например: участок осмотрен, наледь устранена"
                />
              </label>
            </>
          )}
          {formError && (
            <div role="alert" className="alert">
              {formError}
            </div>
          )}
          <button className="primary" disabled={busy}>
            {busy
              ? "Сохраняем…"
              : modal === "report"
                ? "Отправить обращение"
                : "Сохранить решение"}{" "}
            <span>↗</span>
          </button>
        </form>
      </dialog>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
