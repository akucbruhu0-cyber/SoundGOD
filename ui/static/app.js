"use strict";
/* audio-enhance UI. Vanilla on purpose: one page, one server, no build step. */

const TOKEN = document.querySelector('meta[name="token"]').content;
const $ = (s, r = document) => r.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "X-Token": TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const signed = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(1)} dB`;

/* ---- the controls: what each does and how it changes the recording ---- */
const SLIDERS = [
  { k: "gen", g: "engines", type: "seg", label: "מנוע שחזור גנרטיבי (Sidon)", opts: [["true", "פועל"], ["false", "כבוי"]], costKey: "gen",
    what: "מודל שמשחזר את הקול מחדש בצליל נקי ורחב, עד כ-20kHz. הוא נותן עומק ואוויר שחסרים בהקלטה.",
    effect: "בקטע העברי שבדקנו הוא שמר על כל המילים, והצליל יצא טוב יותר מהניקוי לבדו. הוא מנחש את מה שחסר, ולכן בהקלטה חלשה או מהדהדת מאוד כדאי להאזין לתצוגה מקדימה לפני שמחליטים.",
    time: "על זמן העיבוד: כ-20 שניות לדקת הקלטה, איטי יותר מהניקוי. הוא רץ על המעבד בלבד." },
  { k: "clean", g: "engines", type: "seg", label: "מנוע ניקוי (Nemotron)", opts: [["true", "פועל"], ["false", "כבוי"]], costKey: "clean",
    what: "המודל שמסיר רעש והד. הוא החלק הכבד והחשוב ביותר בעבודה.",
    effect: "כבוי: הקובץ רק מוגבר ומלוטש, ונשארים בו הרעש וההד. מתאים להקלטה שכבר נקייה.",
    time: "על זמן העיבוד: זה החלק הכבד, בדרך כלל 70% עד 95% מהזמן. כיבוי מקצר את העבודה פי כמה." },
  { k: "polish", g: "engines", type: "seg", label: "מנוע ליטוש (EQ, שער, דחיסה)", opts: [["true", "פועל"], ["false", "כבוי"]], costKey: "polish",
    what: "עיבוד קלאסי שמעצב את הצליל: סינון נמוכים, שער, חום, נוכחות ודחיסה.",
    effect: "כבוי: רק מתאימים את העוצמה הסופית, בלי לגעת בצבע הקול.",
    time: "על זמן העיבוד: פחות מ-0.4 שניות לכל דקת הקלטה. כיבוי חוסך מעט מאוד." },
  { k: "wet", g: "clean", label: "עוצמת ניקוי", min: 0, max: 100, step: 1, fmt: (v) => `${v}%`,
    what: "כמה מהקול המנוקה נכנס לתוצאה, לעומת ההקלטה המקורית.",
    effect: "100% הוא רק מה שהמודל החזיר: נקי ויבש. פחות משאיר קצת מהחדר, וזה נשמע טבעי יותר וקצת פחות מחוטא.", time: "על זמן העיבוד: לא משפיע. המודל רץ במלואו גם ב-0%; רק היחס בין המקור למנוקה משתנה.", needs: "clean" },
  { k: "chunk", g: "clean", label: "אורך חלק", min: 0.5, max: 5, step: 0.5, fmt: (v) => `${Number(v).toFixed(1)} שנ׳`,
    what: "המודל מעבד את ההקלטה בחתיכות. זה אורך כל חתיכה.",
    effect: "קצר (עד 1.5) מגיב מהר להד שמשתנה. ארוך (4 עד 5) חלק יותר אבל פחות רגיש. בהרצאה שבדקנו, 2 שניות יצא הכי טוב.", time: "על זמן העיבוד: חלקים קצרים מ-2 שניות מאטים את המודל (חצי שנייה לוקחת כ-40% יותר). מעל 2 אין עוד חיסכון.", costKey: "chunk", needs: "clean" },
  { k: "hop", g: "clean", label: "חפיפה בין חלקים", min: 0.5, max: 1, step: 0.25, fmt: (v) => `${Math.round((1 - v) * 100)}%`,
    what: "החלקים שהמודל מעבד נחפפים זה בזה, ובין החלקים מחברים בהדרגה.",
    effect: "50% הוא ברירת המחדל. בלי חפיפה (0%) המודל עובד פי שניים מהר, ובמקרה שבדקנו התוצאה כמעט זהה, אבל ייתכן שבהקלטה עם הד חזק יישמעו תפרים בין החלקים. לא בדקתי את זה על הרצאה, אז כדאי להקשיב בתצוגה מקדימה.",
    time: "על זמן העיבוד: הגדרה משפיעה מאוד. בלי חפיפה זמן המודל יורד בערך בחצי, ב-25% חפיפה בערך שליש.", costKey: "hop", needs: "clean" },
  { k: "bwe", g: "clean", type: "seg", label: "הרחבת תדרים", opts: [["off", "כבוי"], ["32000", "32k"], ["48000", "48k"]],
    what: "מחזיר תדרים גבוהים שחסרים בהקלטה, למשל מטלפון או מאולם.",
    effect: "נותן תחושה של אוויר ופתיחות. המודל ממציא את התדרים האלה, ולכן אצל חלק מהקולות זה יישמע מלאכותי.", time: "על זמן העיבוד: הרחבה מכפילה בערך את זמן המודל (32k בערך פי 2, 48k בערך פי 2.7 לעומת 16k).", costKey: "bwe", needs: "clean" },
  { k: "lufs", g: "polish", label: "עוצמה סופית", min: -23, max: -12, step: 1, fmt: (v) => `${v} LUFS`,
    what: "כמה חזק יוצא הקובץ בסוף.",
    effect: "‎-16 הוא הסטנדרט לסרטונים ופודקאסטים. ‎-14 חזק ובוהק, ‎-20 שקט ונינוח.", time: "על זמן העיבוד: לא משפיע." },
  { k: "presence", g: "polish", label: "נוכחות", min: -6, max: 6, step: 0.5, fmt: signed,
    what: "מדגיש את אזור הבהירות של הדיבור, בסביבות 3kHz.",
    effect: "יותר מחדד עיצורים ונשמע כאילו הדובר קרוב למיקרופון. יותר מדי נשמע חד ומעייף.", time: "על זמן העיבוד: כמעט לא משפיע. כל שרשרת הליטוש מוסיפה פחות מ-0.4 שניות לכל דקת הקלטה.", needs: "polish" },
  { k: "warmth", g: "polish", label: "חום", min: -6, max: 6, step: 0.5, fmt: signed,
    what: "מגביר או מחליש את הבס של הקול, בסביבות 180Hz.",
    effect: "יותר נותן קול עמוק ומלא, כמו ברדיו. פחות נותן קול דק ובהיר.", time: "על זמן העיבוד: כמעט לא משפיע.", needs: "polish" },
  { k: "comp", g: "polish", label: "דחיסה", min: 0, max: 100, step: 1, fmt: (v) => `${v}%`,
    what: "מקרב בין החלקים החלשים של הדיבור לחזקים.",
    effect: "יותר נותן קול אחיד ומקצועי בלי קפיצות. יותר מדי נשמע מעוך וחסר חיים.", time: "על זמן העיבוד: כמעט לא משפיע.", needs: "polish" },
  { k: "gate", g: "polish", label: "שער לזנבות", min: 0, max: 100, step: 1, fmt: (v) => `${v}%`,
    what: "מנמיך את מה שנשאר בין המילים: זנבות הד ורחש.",
    effect: "יותר נותן שקט נקי בין משפטים. מעל 60 זה מתחיל לחתוך הברות חלשות, אז כדאי לשמוע לפני שמחילים.", time: "על זמן העיבוד: כמעט לא משפיע.", needs: "polish" },
  { k: "rate", g: "adv", type: "seg", label: "קצב הדגימה של המודל", opts: [["auto", "אוטומטי"], ["16000", "16k"], ["48000", "48k"]],
    what: "באיזה קצב המודל עובד.",
    effect: "16k מהיר פי שניים וטוב להקלטות חלשות. 48k שומר על תדרים גבוהים בהקלטה איכותית, ואיטי יותר.", time: "על זמן העיבוד: זו ההחלטה הכבדה ביותר בין ההגדרות. 48k איטי בערך פי 2.7 מ-16k.", costKey: "rate", needs: "clean" },
  { k: "pregain", g: "adv", type: "seg", label: "הגברה מוקדמת", opts: [["true", "פועל"], ["false", "כבוי"]],
    what: "מגביר הקלטה חלשה לפני שהמודל מקבל אותה.",
    effect: "בהקלטה חלשה מאוד המודל לא ישמע אותה בלי זה. בהקלטה רגילה אפשר לכבות.", time: "על זמן העיבוד: זניח, מעבר אחד מהיר." },
];
const STAGES = { measure: "מודד", extract: "מחלץ שמע", pregain: "מגביר", download: "מוריד את Sidon (חד-פעמי)", clean: "מנקה רעש והד", gen: "משחזר בצליל נקי (Sidon)", mix: "מערבב", polish: "מלטש", finalize: "שומר קובץ", done: "סיום", starting: "מתחיל" };
const PRESET_LABELS = { auto: "אוטומטי", rescue: "הצלה", studio: "סטודיו", natural: "טבעי" };
const METRICS = [["lufs", "עוצמה (LUFS)"], ["snr_db", "יחס אות לרעש (dB)"], ["noise_floor_db", "רצפת רעש (dB)"], ["bandwidth_hz", "רוחב פס (Hz)"]];

const S = { speed: null, path: null, info: null, presets: {}, preset: "auto", params: {}, dur: 0, start: 0, busy: false, job: null };

/* ---- time estimate: same model as engine/enhance.py estimate() ---- */
function fmtEst(s) {
  if (s < 90) return `${Math.max(1, Math.round(s))} שנ׳`;
  if (s < 5400) return `${Math.round(s / 60)} דק׳`;
  return `${Math.floor(s / 3600)}:${String(Math.round((s % 3600) / 60)).padStart(2, "0")} שעות`;
}

function calc(p, dur) {
  const sp = S.speed;
  if (!sp) return { ai: 0, ff: 0, total: 0 };
  const bw = S.info ? S.info.before.bandwidth_hz : 0;
  const mr = p.rate !== "auto" ? Number(p.rate) : bw > 9000 ? 48000 : 16000;
  const out = p.bwe === "off" ? mr : Math.max(mr, Number(p.bwe));
  const key = out >= 48000 ? "48000" : out >= 32000 ? "32000" : "16000";
  const ai = p.clean ? dur * sp.rtf[key] * (1 + sp.chunk_extra * Math.max(0, 2 - p.chunk) / 1.5) * sp.hop_ref / p.hop : 0;
  const gen = p.gen ? dur * sp.gen_rtf + sp.gen_fixed : 0;
  const ff = sp.fixed + (dur / 60) * (sp.ffmpeg_per_min + (p.polish ? sp.polish_extra_per_min : 0));
  return { ai, gen, ff, total: ai + gen + ff };
}

/* what each setting adds to the time, versus its cheapest value */
const CHEAPEST = { gen: { gen: false }, chunk: { chunk: 2 }, hop: { hop: 1 }, bwe: { bwe: "off" }, rate: { rate: "16000" }, clean: { clean: false }, polish: { polish: false } };
function costOf(d) {
  const dur = S.dur || 60, p = S.params;
  const total = calc(p, dur).total;
  const add = d.costKey ? Math.max(0, total - calc({ ...p, ...CHEAPEST[d.costKey] }, dur).total) : 0;
  const share = total ? add / total : 0;
  const l = add < 1 || share < 0.03 ? 0 : share < 0.15 ? 1 : share < 0.5 ? 2 : 3;
  const scope = S.dur ? "" : " לדקה";
  const text = l === 0 ? "לא מוסיף זמן" : `מוסיף כ-${fmtEst(add)}${scope}`;
  return { l, text };
}

function updateEstimate() {
  if (S.busy || !S.dur || !S.speed) return;
  const e = calc(S.params, S.dur), pv = calc(S.params, Math.min(15, S.dur));
  $("#bar-status").innerHTML = `זמן עיבוד משוער לכל ההקלטה: <b>${fmtEst(e.total)}</b>` +
    (e.ai || e.gen ? ` <small>(${[e.ai ? `ניקוי ${fmtEst(e.ai)}` : "", e.gen ? `שחזור ${fmtEst(e.gen)}` : "", `שאר העיבוד ${fmtEst(e.ff)}`].filter(Boolean).join(" · ")})</small>` : "");
  $("#preview").textContent = `תצוגה מקדימה · 15 שניות · כ-${fmtEst(pv.total)}`;
}

/* ---- rendering the controls ---- */
function setFill(input) {
  const p = ((input.value - input.min) / (input.max - input.min)) * 100;
  input.style.setProperty("--p", `${p}%`);
}

function renderControls() {
  for (const g of ["engines", "clean", "polish", "adv"]) $(`#sliders-${g}`).replaceChildren();
  for (const d of SLIDERS) {
    const row = document.createElement("div");
    row.className = "slider-row";
    const head = document.createElement("div");
    head.className = "row";
    const name = document.createElement("span");
    name.className = "name";
    name.append(d.label);
    const cost = document.createElement("span");
    cost.className = "cost";
    cost.innerHTML = "<i></i><i></i><i></i><em></em>";
    cost.title = "כמה זמן עיבוד ההגדרה הזו מוסיפה";
    name.append(cost);
    d.cost = cost;
    const val = document.createElement("span");
    val.className = "val";
    head.append(name, val);
    row.append(head);
    if (d.type === "seg") {
      const seg = document.createElement("div");
      seg.className = "seg";
      seg.style.marginBlockStart = "8px";
      for (const [v, text] of d.opts) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = text;
        b.dataset.v = v;
        b.onclick = () => { S.params[d.k] = ["pregain", "clean", "gen", "polish"].includes(d.k) ? v === "true" : v; if (d.g === "engines") S.enginesTouched = true; markCustom(); syncControls(); };
        seg.append(b);
      }
      row.append(seg);
      d.el = seg;
    } else {
      const input = document.createElement("input");
      input.type = "range";
      Object.assign(input, { min: d.min, max: d.max, step: d.step });
      input.setAttribute("aria-label", d.label);
      input.oninput = () => { S.params[d.k] = Number(input.value); markCustom(); syncControls(); };
      row.append(input);
      d.el = input;
    }
    const what = document.createElement("p");
    what.className = "desc what";
    what.textContent = d.what;
    const effect = document.createElement("p");
    effect.className = "desc effect";
    effect.textContent = d.effect;
    row.append(what, effect);
    if (d.time) {
      const time = document.createElement("p");
      time.className = "desc time";
      time.textContent = d.time;
      d.timeEl = time;
      row.append(time);
    }
    d.row = row;
    d.val = val;
    $(`#sliders-${d.g}`).append(row);
  }
  const box = $("#presets");
  box.replaceChildren();
  for (const k of ["auto", "rescue", "studio", "natural"]) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip-btn";
    b.dataset.k = k;
    b.onclick = () => applyPreset(k);
    box.append(b);
  }
}

function syncControls() {
  for (const d of SLIDERS) {
    const v = S.params[d.k];
    const c = costOf(d);
    d.cost.dataset.l = c.l;
    d.cost.lastElementChild.textContent = c.text;
    const off = Boolean(d.needs) && S.params[d.needs] === false;
    d.row.classList.toggle("off", off);
    for (const el of d.el.matches("input") ? [d.el] : d.el.children) el.disabled = off;
    if (d.type === "seg") {
      for (const b of d.el.children) b.classList.toggle("on", b.dataset.v === String(v));
      d.val.textContent = "";
    } else {
      d.el.value = v;
      setFill(d.el);
      d.val.textContent = d.fmt(v);
    }
  }
  for (const b of $("#presets").children) {
    b.setAttribute("aria-pressed", String(b.dataset.k === S.preset));
    const suggested = S.info ? S.info.suggested_preset : null;
    b.innerHTML = PRESET_LABELS[b.dataset.k] + (b.dataset.k === "auto" && suggested ? `<small>${PRESET_LABELS[suggested]}</small>` : "");
  }
  updateEstimate();
}

function applyPreset(k) {
  S.preset = k;
  const real = k === "auto" ? (S.info ? S.info.suggested_preset : "studio") : k;
  // the presets pick their own engines; once the user has flipped an engine by hand, presets leave it alone
  const keep = S.enginesTouched ? { clean: S.params.clean, gen: S.params.gen, polish: S.params.polish } : {};
  S.params = { ...S.presets[real], ...keep };
  S.params.rate = String(S.params.rate);
  S.params.bwe = String(S.params.bwe);
  syncControls();
}
const markCustom = () => { S.preset = "custom"; };

/* ---- jobs ---- */
function setBusy(on, label = "") {
  S.busy = on;
  $("#wrap").classList.toggle("working", on);
  for (const id of ["apply", "preview", "pick"]) $("#" + id).disabled = on || (id !== "pick" && !S.path);
  $("#cancel").hidden = !on;
  $("#progress").hidden = !on;
  $("#bar-status").textContent = on ? label : "";
  if (!on) updateEstimate();
}

function note(text) {
  const n = $("#note");
  n.hidden = !text;
  n.textContent = text || "";
}

async function runJob(kind, extra = {}, label = "") {
  setBusy(true, label);
  note("");
  const { job } = await api(`/api/${kind}`, { path: S.path, params: S.params, ...extra });
  S.job = job;
  const t0 = Date.now();
  for (;;) {
    const j = await api(`/api/job/${job}`);
    // the model stage is one long call with no progress output, so estimate it from the expected speed
    let pct = j.pct, label = STAGES[j.stage] || j.stage;
    if (j.eta && j.to) {
      const el = Date.now() / 1000 - j.t;
      pct = Math.round(j.pct + (j.to - j.pct) * Math.min(el / j.eta, 0.97));
      const left = Math.max(j.eta - el, 0);
      label += left > 90 ? ` · נשארו כ-${Math.ceil(left / 60)} דק׳ (הערכה)` : el > j.eta ? " · מסיים…" : " · פחות מדקה וחצי";
    }
    const sec = Math.floor((Date.now() - t0) / 1000);
    label += ` · עבר ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    $("#progress-label").textContent = label;
    $("#progress-pct").textContent = `${pct}%`;
    $("#bar").style.width = `${pct}%`;
    if (j.state !== "running") { j.id = job; return j; }
    await sleep(400);
  }
}

async function guarded(fn) {
  try { await fn(); } catch (e) { note(`משהו השתבש: ${e.message}`); } finally { setBusy(false); }
}

/* ---- file ---- */
async function loadFile(path) {
  S.path = path;
  $("#file-empty").hidden = true;
  await guarded(async () => {
    const j = await runJob("analyze", {}, "מנתח את הקובץ…");
    if (j.state === "error") throw new Error(j.error);
    S.info = j.result;
    const b = S.info.before;
    S.dur = b.duration;
    $("#file-info").hidden = false;
    $("#fname").textContent = path.split("/").pop();
    $("#fdur").textContent = fmtTime(b.duration);
    $("#facts").innerHTML = [["עוצמה", `${b.lufs} LUFS`], ["אות לרעש", `${b.snr_db} dB`], ["רצפת רעש", `${b.noise_floor_db} dB`], ["רוחב פס", `${b.bandwidth_hz} Hz`]]
      .map(([k, v]) => `<span class="fact">${k} <b dir="ltr">${v}</b></span>`).join("");
    const why = b.lufs < -35 ? "ההקלטה חלשה מאוד" : b.snr_db < 18 ? "יחס האות לרעש נמוך" : "ההקלטה במצב טוב";
    $("#suggest").textContent = `${why}, ולכן מוצע פריסט ${PRESET_LABELS[S.info.suggested_preset]}. אפשר לשנות כל סקאלה.`;
    const start = $("#start");
    start.max = Math.max(0, Math.floor(b.duration - 15));
    start.value = Math.floor(Math.min(b.duration * 0.3, start.max));
    S.start = Number(start.value);
    $("#start-val").textContent = fmtTime(S.start);
    setFill(start);
    applyPreset("auto");
    $("#stage-empty").hidden = true;
    $("#stage-status").textContent = "מוכן";
  });
  setBusy(false);
}

/* ---- results ---- */
function renderMetrics(before, after, bh, ah) {
  const t = $("#metrics");
  t.hidden = false;
  $("#m-before-h").textContent = bh;
  $("#m-after-h").textContent = ah;
  $("tbody", t).innerHTML = METRICS.map(([k, label]) => {
    const gain = k === "snr_db" && after[k] - before[k] >= 3 ? " gain" : "";
    return `<tr><td>${label}</td><td dir="ltr">${before[k]}</td><td dir="ltr" class="${gain.trim()}">${after[k]}</td></tr>`;
  }).join("");
}

const AB = { before: null, after: null, mode: "after", data: {}, raf: 0 };

async function loadWave(which, url) {
  const buf = await (await fetch(url)).arrayBuffer();
  const ctx = new AudioContext();
  const audio = await ctx.decodeAudioData(buf);
  ctx.close();
  const ch = audio.getChannelData(0), bins = 800, step = Math.floor(ch.length / bins), peaks = new Float32Array(bins);
  for (let i = 0; i < bins; i++) {
    let m = 0;
    for (let j = i * step; j < (i + 1) * step; j++) m = Math.max(m, Math.abs(ch[j]));
    peaks[i] = m;
  }
  AB.data[which] = peaks;
}

function drawWave(which) {
  const c = $(`#wave-${which}`), peaks = AB.data[which];
  if (!peaks) return;
  const dpr = devicePixelRatio || 1;
  c.width = c.clientWidth * dpr;
  c.height = 64 * dpr;
  const g = c.getContext("2d"), css = getComputedStyle(document.documentElement);
  g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = css.getPropertyValue(which === "after" ? "--forest" : "--muted");
  const w = c.width / peaks.length;
  for (let i = 0; i < peaks.length; i++) {
    const h = Math.max(2 * dpr, peaks[i] * c.height * 0.9);
    g.fillRect(i * w, (c.height - h) / 2, Math.max(1, w - 1), h);
  }
  const a = AB[AB.mode];
  if (a && a.duration) {
    g.fillStyle = css.getPropertyValue("--ink");
    g.fillRect((a.currentTime / a.duration) * c.width, 0, 2 * dpr, c.height);
  }
}

function tick() {
  const m = AB[AB.mode], o = AB[AB.mode === "after" ? "before" : "after"];
  if (m && o && Math.abs(m.currentTime - o.currentTime) > 0.05) o.currentTime = m.currentTime;
  $("#time").textContent = `${fmtTime(m.currentTime)} / ${fmtTime(m.duration || 0)}`;
  drawWave("before"); drawWave("after");
  if (!m.paused) AB.raf = requestAnimationFrame(tick);
  else $("#play").textContent = "▶";
}

function setMode(mode) {
  AB.mode = mode;
  if (AB.before) { AB.before.muted = mode !== "before"; AB.after.muted = mode !== "after"; }
  for (const b of document.querySelectorAll(".seg [data-mode]")) b.classList.toggle("on", b.dataset.mode === mode);
}

async function showPreview(job) {
  const u = (f) => `/media/${job}/${f}?t=${encodeURIComponent(TOKEN)}`;
  for (const k of ["before", "after"]) { if (AB[k]) AB[k].pause(); AB[k] = new Audio(u(`${k}.wav`)); AB[k].preload = "auto"; $(`#spec-${k}`).src = u(`${k}.png`); }
  AB.data = {};
  $("#ab").hidden = false;
  setMode("after");
  $("#play").textContent = "▶";
  await Promise.all([loadWave("before", u("before.wav")), loadWave("after", u("after.wav"))]);
  drawWave("before"); drawWave("after");
}

/* ---- actions ---- */
async function doPreview() {
  await guarded(async () => {
    const dur = Math.min(15, Math.max(3, S.dur - S.start));
    const j = await runJob("preview", { start: S.start, dur }, "מכין תצוגה מקדימה…");
    if (j.state === "error") throw new Error(j.error);
    $("#saved").hidden = true;
    renderMetrics(S.info.before, j.result.after, "מקור (כל הקובץ)", `אחרי (${Math.round(dur)} שנ׳)`);
    await showPreview(j.id);
    $("#stage-status").textContent = `תצוגה · ${j.result.seconds} שנ׳`;
  });
}

async function doApply() {
  await guarded(async () => {
    const j = await runJob("run", {}, "מעבד את כל ההקלטה…");
    if (j.state === "cancelled") return note("העיבוד בוטל. הקובץ המקורי לא השתנה.");
    if (j.state === "error") throw new Error(j.error);
    renderMetrics(j.result.before, j.result.after, "לפני", "אחרי");
    $("#saved").hidden = false;
    $("#saved-path").textContent = j.result.output;
    S.output = j.result.output;
    $("#stage-status").textContent = `נשמר · ${j.result.seconds} שנ׳`;
  });
}

/* ---- wiring ---- */
$("#pick").onclick = async () => {
  try {
    $("#bar-status").textContent = "ממתין לבחירת קובץ…";
    const { path } = await api("/api/pick", {});
    $("#bar-status").textContent = "";
    if (path) await loadFile(path);
  } catch (e) { note(`משהו השתבש: ${e.message}`); }
};
$("#preview").onclick = doPreview;
$("#apply").onclick = doApply;
$("#cancel").onclick = () => S.job && api("/api/cancel", { job: S.job });
$("#reveal").onclick = () => S.output && api("/api/reveal", { path: S.output });
$("#start").oninput = (e) => { S.start = Number(e.target.value); $("#start-val").textContent = fmtTime(S.start); setFill(e.target); };
$("#play").onclick = () => {
  const m = AB[AB.mode];
  if (!m) return;
  if (m.paused) { AB.before.play(); AB.after.play(); $("#play").textContent = "❚❚"; tick(); }
  else { AB.before.pause(); AB.after.pause(); }
};
for (const b of document.querySelectorAll(".seg [data-mode]")) b.onclick = () => setMode(b.dataset.mode);
for (const w of ["before", "after"]) {
  $(`#wave-${w}`).onclick = (e) => {
    const m = AB[AB.mode];
    if (!m || !m.duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    AB.before.currentTime = AB.after.currentTime = ((e.clientX - r.left) / r.width) * m.duration;
    tick();
  };
}

setInterval(() => api("/api/ping").catch(() => {}), 30000);  // keeps the launcher's idle shutdown away while the page is open

(async () => {
  renderControls();
  const d = await api("/api/describe");
  S.presets = d.presets;
  S.speed = d.speed;
  const gen = SLIDERS.find((x) => x.k === "gen");
  if (!d.sidon_ready) gen.timeEl.textContent += " בהפעלה הראשונה יורדים כ-1.7GB (אוטומטית, כמה דקות).";
  applyPreset("studio");
  $("#bar-status").textContent = "בחר קובץ כדי להתחיל";
  $("#pick").disabled = false;
})().catch((e) => note(`לא הצלחתי להתחבר לשרת: ${e.message}`));
