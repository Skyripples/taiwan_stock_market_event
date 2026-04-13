const calendarGrid = document.getElementById("calendarGrid");
const monthTitle = document.getElementById("monthTitle");
const updateInfo = document.getElementById("updateInfo");

const todayBtn = document.getElementById("todayBtn");
const prevBtn = document.getElementById("prevBtn");
const nextBtn = document.getElementById("nextBtn");

let currentDate = new Date();
let allEvents = [];

const EVENT_LABEL = {
  dividend: "除權息",
};

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatDateLocal(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function toDateOnly(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
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

    const dayEvents = allEvents
      .filter((e) => e.date === dateStr)
      .sort((a, b) => (a.type > b.type ? 1 : -1));

    const visibleEvents = dayEvents.slice(0, 3);

    for (const ev of visibleEvents) {
      const a = document.createElement("a");
      a.className = `event-pill ${ev.type}`;
      a.href = ev.url || "#";
      a.target = "_blank";
      a.rel = "noreferrer";
      a.title = `[${EVENT_LABEL[ev.type] || ev.type}] ${ev.title}`;
      a.textContent = `【${EVENT_LABEL[ev.type] || ev.type}】${ev.title}`;
      eventsWrap.appendChild(a);
    }

    if (dayEvents.length > 3) {
      const more = document.createElement("div");
      more.className = "more-text";
      more.textContent = `+${dayEvents.length - 3} more`;
      eventsWrap.appendChild(more);
    }

    cell.appendChild(number);
    cell.appendChild(eventsWrap);
    calendarGrid.appendChild(cell);
  }
}

async function loadEvents() {
  try {
    const res = await fetch(`./data/event.json?t=${Date.now()}`);
    const data = await res.json();
    allEvents = Array.isArray(data.events) ? data.events : [];

    const updatedAt = data.updated_at_taipei || data.updated_at_utc || "未知";
    updateInfo.textContent = `最後更新：${updatedAt}`;
  } catch (err) {
    console.error(err);
    updateInfo.textContent = "事件資料載入失敗";
    allEvents = [];
  }

  renderCalendar();
}

todayBtn.addEventListener("click", () => {
  currentDate = new Date();
  renderCalendar();
});

prevBtn.addEventListener("click", () => {
  currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() - 1, 1);
  renderCalendar();
});

nextBtn.addEventListener("click", () => {
  currentDate = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 1);
  renderCalendar();
});

loadEvents();
