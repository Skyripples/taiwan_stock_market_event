const calendarGrid = document.getElementById("calendarGrid");
const monthTitle = document.getElementById("monthTitle");
const updateInfo = document.getElementById("updateInfo");

const todayBtn = document.getElementById("todayBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");
const stockSelect = document.getElementById("stockSelect");
const themeToggleSwitch = document.getElementById("themeToggleSwitch");

const eventModal = document.getElementById("eventModal");
const modalBackdrop = document.getElementById("modalBackdrop");
const closeModalBtn = document.getElementById("closeModalBtn");
const modalTitle = document.getElementById("modalTitle");
const modalBody = document.getElementById("modalBody");

let currentDate = new Date();
let allEvents = [];
let isReloading = false;
const STOCK_ALL_VALUE = "__ALL__";
let selectedStockId = STOCK_ALL_VALUE;
const THEME_STORAGE_KEY = "taiwan_stock_market_theme";

const EVENT_LABEL = {
  dividend: "除權息",
  dividend_payment: "股利發放日",
  earnings_call: "法說會",
  shareholder_meeting: "股東會",
  delisting: "終止掛牌",
  material_info: "重大訊息",
  revenue: "月營收",
};

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatDateLocal(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function getMonthMatrix(year, month) {
  const firstDay = new Date(year, month, 1);
  const firstWeekday = firstDay.getDay();

  const startDate = new Date(year, month, 1 - firstWeekday);
  const cells = [];

  for (let i = 0; i < 42; i += 1) {
    const d = new Date(startDate);
    d.setDate(startDate.getDate() + i);
    cells.push(d);
  }

  return cells;
}

function getDisplayText(eventItem) {
  if (eventItem.type === "dividend_payment" && eventItem.title) {
    return eventItem.title;
  }
  const typeText = EVENT_LABEL[eventItem.type] || eventItem.type;
  return `${eventItem.stock_id} ${eventItem.stock_name}(${typeText})`;
}

function appendMetaLine(metaNode, label, value) {
  const line = document.createElement("div");
  const text = String(value || "").trim();
  line.textContent = `${label}：${text || "-"}`;
  metaNode.appendChild(line);
}

function appendSourceAndLink(metaNode, ev) {
  appendMetaLine(metaNode, "來源", ev.source || "未知");
  if (!ev.url) return;

  const link = document.createElement("a");
  link.className = "detail-link";
  link.href = ev.url;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "查看原始來源";
  metaNode.appendChild(link);
}

function buildMetaByType(metaNode, ev) {
  if (ev.type === "earnings_call" || ev.type === "shareholder_meeting") {
    appendMetaLine(metaNode, "日期", ev.date);
    appendMetaLine(metaNode, "時間", ev.time);
    return;
  }

  if (ev.type === "dividend" || ev.type === "dividend_payment") {
    const exDate = ev.ex_date || (ev.type === "dividend" ? ev.date : "");
    const payDate = ev.pay_date || (ev.type === "dividend_payment" ? ev.date : "");

    appendMetaLine(metaNode, "除權息日", exDate);
    appendMetaLine(metaNode, "發放日期", payDate);
    appendMetaLine(metaNode, "現金股利", ev.cash_dividend);
    return;
  }

  appendMetaLine(metaNode, "日期", ev.date);
  if (ev.time) {
    appendMetaLine(metaNode, "時間", ev.time);
  }
  appendSourceAndLink(metaNode, ev);
}

function openModal(dateStr, dayEvents) {
  const dt = new Date(`${dateStr}T00:00:00`);
  modalTitle.textContent = dt.toLocaleDateString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "long",
  });

  modalBody.innerHTML = "";

  if (!dayEvents.length) {
    const empty = document.createElement("div");
    empty.className = "modal-empty";
    empty.textContent = "當天沒有事件。";
    modalBody.appendChild(empty);
  } else {
    dayEvents.forEach((ev) => {
      const card = document.createElement("div");
      card.className = "detail-card";

      const type = document.createElement("div");
      type.className = `detail-type ${ev.type}`;
      type.textContent = EVENT_LABEL[ev.type] || ev.type;

      const title = document.createElement("h4");
      title.className = "detail-title";
      title.textContent = ev.type === "dividend_payment" && ev.title
        ? ev.title
        : `${ev.stock_id} ${ev.stock_name}`;

      const meta = document.createElement("div");
      meta.className = "detail-meta";
      buildMetaByType(meta, ev);

      card.appendChild(type);
      card.appendChild(title);
      card.appendChild(meta);

      modalBody.appendChild(card);
    });
  }

  eventModal.classList.remove("hidden");
}

function closeModal() {
  eventModal.classList.add("hidden");
}

function getPreferredTheme() {
  try {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (savedTheme === "light" || savedTheme === "dark") {
      return savedTheme;
    }
  } catch (err) {
    // Ignore localStorage access issues and fall back to system preference.
  }

  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }

  return "light";
}

function applyTheme(theme) {
  const isDark = theme === "dark";
  document.body.classList.toggle("theme-dark", isDark);
  document.body.classList.toggle("theme-light", !isDark);

  if (themeToggleSwitch) {
    themeToggleSwitch.checked = isDark;
    themeToggleSwitch.setAttribute("aria-checked", isDark ? "true" : "false");
  }
}

function setTheme(theme, options = {}) {
  const { persist = true } = options;
  applyTheme(theme);
  if (!persist) return;

  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (err) {
    // Ignore localStorage access issues.
  }
}

function getFilteredEvents() {
  if (selectedStockId === STOCK_ALL_VALUE) {
    return allEvents;
  }
  return allEvents.filter((e) => String(e.stock_id) === selectedStockId);
}

function rebuildStockSelectOptions() {
  if (!stockSelect) return;

  const uniqueStocks = new Map();
  for (const ev of allEvents) {
    const stockId = String(ev.stock_id || "").trim();
    if (!stockId) continue;
    if (!uniqueStocks.has(stockId)) {
      uniqueStocks.set(stockId, String(ev.stock_name || "").trim());
    }
  }

  const sortedStocks = Array.from(uniqueStocks.entries()).sort((a, b) => {
    if (a[0] !== b[0]) {
      return a[0].localeCompare(b[0], "zh-Hant-u-kn-true");
    }
    return a[1].localeCompare(b[1], "zh-Hant");
  });

  const prevSelectedStockId = selectedStockId;
  stockSelect.innerHTML = "";

  const allOption = document.createElement("option");
  allOption.value = STOCK_ALL_VALUE;
  allOption.textContent = "全部股票";
  stockSelect.appendChild(allOption);

  for (const [stockId, stockName] of sortedStocks) {
    const option = document.createElement("option");
    option.value = stockId;
    option.textContent = `${stockId} ${stockName}`.trim();
    stockSelect.appendChild(option);
  }

  const hasPrevSelection = sortedStocks.some(([stockId]) => stockId === prevSelectedStockId);
  selectedStockId = hasPrevSelection ? prevSelectedStockId : STOCK_ALL_VALUE;
  stockSelect.value = selectedStockId;
}

function renderCalendar() {
  calendarGrid.innerHTML = "";

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  monthTitle.textContent = currentDate.toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
  });

  const cells = getMonthMatrix(year, month);
  const todayStr = formatDateLocal(new Date());
  const eventsForRender = getFilteredEvents();

  for (const cellDate of cells) {
    const cell = document.createElement("div");
    cell.className = "day-cell";

    const dateStr = formatDateLocal(cellDate);
    const isOtherMonth = cellDate.getMonth() !== month;

    if (isOtherMonth) {
      cell.classList.add("other-month");
    }

    if (dateStr === todayStr) {
      cell.classList.add("today");
    }

    const number = document.createElement("div");
    number.className = "day-number";
    number.textContent = pad2(cellDate.getDate());

    const eventsWrap = document.createElement("div");
    eventsWrap.className = "day-events";

    const dayEvents = eventsForRender
      .filter((e) => e.date === dateStr)
      .sort((a, b) => {
        if (String(a.stock_id) !== String(b.stock_id)) {
          return String(a.stock_id).localeCompare(String(b.stock_id));
        }
        return String(a.stock_name).localeCompare(String(b.stock_name), "zh-Hant");
      });

    const visibleEvents = dayEvents.slice(0, 3);

    for (const ev of visibleEvents) {
      const a = document.createElement("a");
      a.className = `event-pill ${ev.type}`;
      a.href = ev.url || "#";
      a.target = "_blank";
      a.rel = "noreferrer";
      a.title = getDisplayText(ev);
      a.textContent = getDisplayText(ev);
      a.addEventListener("click", (evt) => {
        evt.stopPropagation();
      });
      eventsWrap.appendChild(a);
    }

    if (dayEvents.length > 3) {
      const more = document.createElement("div");
      more.className = "more-text";
      more.textContent = `more(共${dayEvents.length}項)`;
      eventsWrap.appendChild(more);
    }

    cell.appendChild(number);
    cell.appendChild(eventsWrap);

    cell.addEventListener("click", () => {
      openModal(dateStr, dayEvents);
    });

    calendarGrid.appendChild(cell);
  }
}

async function loadEvents() {
  if (isReloading) return;

  isReloading = true;

  try {
    const res = await fetch(`./data/event.json?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    allEvents = Array.isArray(data.events) ? data.events : [];
    rebuildStockSelectOptions();

    const updatedAt = data.updated_at_taipei || data.updated_at_utc || "未知";
    updateInfo.textContent = `最後更新：${updatedAt}｜共 ${allEvents.length} 筆事件`;
  } catch (err) {
    console.error(err);
    updateInfo.textContent = "載入事件失敗，請稍後再試";
    allEvents = [];
    rebuildStockSelectOptions();
  } finally {
    isReloading = false;
    renderCalendar();
  }
}

todayBtn.addEventListener("click", () => {
  currentDate = new Date();
  renderCalendar();
});

if (stockSelect) {
  stockSelect.addEventListener("change", () => {
    selectedStockId = stockSelect.value || STOCK_ALL_VALUE;
    closeModal();
    renderCalendar();
  });
}

if (themeToggleSwitch) {
  themeToggleSwitch.addEventListener("change", () => {
    setTheme(themeToggleSwitch.checked ? "dark" : "light");
  });
}

prevBtn.addEventListener("click", () => {
  currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1);
  renderCalendar();
});

nextBtn.addEventListener("click", () => {
  currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1);
  renderCalendar();
});

modalBackdrop.addEventListener("click", closeModal);
closeModalBtn.addEventListener("click", closeModal);

document.addEventListener("keydown", (evt) => {
  if (evt.key === "Escape") {
    closeModal();
  }
});

setTheme(getPreferredTheme(), { persist: false });
loadEvents();
