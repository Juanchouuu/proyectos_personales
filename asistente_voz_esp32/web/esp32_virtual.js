/* ESP32-S3 virtual: reproduce en el navegador lo que haría el firmware real.
 *
 *  - "Pulsador"  -> botón en pantalla / barra espaciadora
 *  - "INMP441"   -> micrófono del computador, remuestreado a 16 kHz · 16 bits · mono
 *  - "Wi-Fi"     -> petición HTTP POST al servidor Python, con token
 *  - "MAX98357A" -> parlantes del computador
 */
"use strict";

const FRECUENCIA = 16000;
const $ = (id) => document.getElementById(id);

const estado = {
  encendido: false,
  conectado: false,
  ocupado: false,       // enviando o reproduciendo: se ignora el botón, como en el firmware
  grabando: false,
  inicioBoot: 0,
  ctx: null,
  stream: null,
  trozos: [],
  inicioGrabacion: 0,
  temporizador: null,
  maxSegundos: 10,
  ultimaGrabacion: null,
};

// ------------------------------------------------------------------ utilidades

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

function cfg() {
  return {
    ssid: $("cfg-ssid").value.trim(),
    url: $("cfg-url").value.trim().replace(/\/+$/, ""),
    token: $("cfg-token").value.trim(),
    id: $("cfg-id").value.trim() || "esp32-virtual",
  };
}

function guardarConfig() {
  try {
    const { ssid, url, token, id } = cfg();
    localStorage.setItem("esp32-virtual", JSON.stringify({ ssid, url, token, id }));
  } catch (_) { /* almacenamiento no disponible */ }
}

function cargarConfig() {
  $("cfg-url").value = location.protocol.startsWith("http") ? location.origin : "http://localhost:8000";
  try {
    const g = JSON.parse(localStorage.getItem("esp32-virtual") || "{}");
    if (g.ssid) $("cfg-ssid").value = g.ssid;
    if (g.url) $("cfg-url").value = g.url;
    if (g.token) $("cfg-token").value = g.token;
    if (g.id) $("cfg-id").value = g.id;
  } catch (_) { /* sin datos guardados */ }
}

function serial(actor, mensaje, clase = "") {
  const ms = estado.inicioBoot ? Math.round(performance.now() - estado.inicioBoot) : 0;
  const etiqueta = { esp32: "ESP32", servidor: "SERVIDOR", ia: "IA" }[actor] || actor.toUpperCase();
  const linea = document.createElement("span");
  linea.innerHTML =
    `<span class="t">[${String(ms).padStart(7, " ")}]</span> ` +
    `<span class="a-${actor}">[${etiqueta}]</span> `;
  const texto = document.createElement("span");
  texto.className = clase;
  texto.textContent = mensaje + "\n";
  linea.appendChild(texto);
  const m = $("monitor");
  m.appendChild(linea);
  m.scrollTop = m.scrollHeight;
}

function led(id, color, modo = "on") {
  const el = $(id);
  el.className = "led";
  if (modo !== "off") el.classList.add("on", color);
  if (modo === "parpadeo") el.classList.add("parpadeo");
}

function ponerEstado(texto) { $("estado").textContent = texto; }

function flujo(indices, clase) {
  const items = $("flujo").children;
  for (const i of indices) {
    items[i].classList.remove("activo", "hecho", "fallo");
    if (clase) items[i].classList.add(clase);
  }
}
const limpiarFlujo = () => flujo([0, 1, 2, 3, 4, 5, 6, 7], null);

function actualizarBotones() {
  const listo = estado.encendido && estado.conectado && !estado.ocupado;
  $("btn-hablar").disabled = !(listo && estado.stream);
  $("btn-contexto").disabled = !listo;
  $("archivo").parentElement.classList.toggle("deshabilitado", !listo);
  $("btn-escuchar").disabled = !estado.ultimaGrabacion;
  $("btn-descargar").classList.toggle("deshabilitado", !estado.ultimaGrabacion);
}

/** Pitidos locales: lo que haría el firmware cuando no hay audio del servidor. */
function pitidoError() {
  try {
    const ctx = estado.ctx || new AudioContext();
    [0, 0.22].forEach((t, i) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = i ? 330 : 440;
      g.gain.setValueAtTime(0.15, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.18);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t);
      o.stop(ctx.currentTime + t + 0.2);
    });
  } catch (_) { /* sin audio */ }
}

// ------------------------------------------------------------------ audio

const CODIGO_WORKLET = `
class Captura extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.n = 0; }
  process(inputs) {
    const canal = inputs[0] && inputs[0][0];
    if (canal) {
      this.buf.push(canal.slice(0)); this.n += canal.length;
      if (this.n >= 2048) {
        const out = new Float32Array(this.n); let o = 0;
        for (const b of this.buf) { out.set(b, o); o += b.length; }
        this.port.postMessage(out, [out.buffer]); this.buf = []; this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor("captura", Captura);`;

async function iniciarMicrofono() {
  estado.ctx = estado.ctx || new AudioContext();
  await estado.ctx.resume();
  estado.stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const url = URL.createObjectURL(new Blob([CODIGO_WORKLET], { type: "application/javascript" }));
  await estado.ctx.audioWorklet.addModule(url);
  const fuente = estado.ctx.createMediaStreamSource(estado.stream);
  const nodo = new AudioWorkletNode(estado.ctx, "captura");
  const silencio = estado.ctx.createGain();
  silencio.gain.value = 0;
  fuente.connect(nodo).connect(silencio).connect(estado.ctx.destination);
  nodo.port.onmessage = (e) => {
    if (!estado.grabando) return;
    estado.trozos.push(e.data);
    let suma = 0;
    for (const v of e.data) suma += v * v;
    const rms = Math.sqrt(suma / e.data.length);
    $("nivel").style.width = Math.min(100, rms * 400) + "%";
  };
}

function detenerMicrofono() {
  if (estado.stream) estado.stream.getTracks().forEach((t) => t.stop());
  estado.stream = null;
}

/** Remuestrea a 16 kHz con OfflineAudioContext (incluye filtro anti-aliasing). */
async function remuestrear(muestras, frecuenciaOrigen) {
  if (frecuenciaOrigen === FRECUENCIA) return muestras;
  const largo = Math.ceil((muestras.length * FRECUENCIA) / frecuenciaOrigen);
  const off = new OfflineAudioContext(1, largo, FRECUENCIA);
  const buf = off.createBuffer(1, muestras.length, frecuenciaOrigen);
  buf.copyToChannel(muestras, 0);
  const src = off.createBufferSource();
  src.buffer = buf;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

/** Float32 [-1,1] -> WAV PCM 16 bits mono (igual al buffer que arma el firmware). */
function crearWav(muestras) {
  const n = muestras.length;
  const ab = new ArrayBuffer(44 + n * 2);
  const v = new DataView(ab);
  const txt = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  txt(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); txt(8, "WAVE");
  txt(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, FRECUENCIA, true); v.setUint32(28, FRECUENCIA * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  txt(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, muestras[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([ab], { type: "audio/wav" });
}

function guardarGrabacion(wav) {
  estado.ultimaGrabacion = wav;
  const a = $("btn-descargar");
  if (a.href) URL.revokeObjectURL(a.href);
  a.href = URL.createObjectURL(wav);
  actualizarBotones();
}

// ------------------------------------------------------------------ encendido y Wi-Fi

async function encender() {
  if (estado.encendido) return apagar();
  guardarConfig();
  estado.encendido = true;
  estado.inicioBoot = performance.now();
  $("monitor").textContent = "";
  $("btn-encender").textContent = "⏻ Apagar ESP32";
  led("led-power", "verde");
  ponerEstado("ARRANCANDO");
  serial("esp32", "ESP-ROM:esp32s3-20210327 · Asistente de voz v1.0");
  serial("esp32", "PSRAM: 8 MB · Flash: 16 MB");

  try {
    await iniciarMicrofono();
    serial("esp32", `I2S0 (INMP441) listo: ${FRECUENCIA} Hz, 16 bits, mono  [mic del PC a ${estado.ctx.sampleRate} Hz → remuestreo]`);
    serial("esp32", "I2S1 (MAX98357A) listo: 16000 Hz, 16 bits, mono");
  } catch (e) {
    serial("esp32", `Error iniciando micrófono: ${e.message}. Puedes enviar archivos de audio.`, "err");
  }
  await conectarWifi();
}

async function conectarWifi() {
  const { ssid, url } = cfg();
  ponerEstado("WIFI...");
  led("led-wifi", "azul", "parpadeo");
  serial("esp32", `Conectando a Wi-Fi "${ssid}"...`);
  await espera(700);
  serial("esp32", "Wi-Fi conectado. IP: 192.168.1.77 (simulada)");
  serial("esp32", `Comprobando servidor ${url}/api/salud ...`);
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch(`${url}/api/salud`, { signal: ctrl.signal });
    clearTimeout(t);
    const info = await r.json();
    estado.maxSegundos = info.limites.max_segundos_grabacion;
    estado.conectado = true;
    led("led-wifi", "azul");
    serial("servidor", `OK · STT=${info.proveedores.stt} · LLM=${info.proveedores.llm} · TTS=${info.proveedores.tts}`, "ok");
    serial("servidor", `Límites: grabación ≤ ${estado.maxSegundos} s · respuesta ≤ ${info.limites.max_caracteres_respuesta} caracteres`);
    ponerEstado("LISTO");
    serial("esp32", "Listo. Mantén presionado el botón para hablar.", "ok");
    actualizarRegistro();
  } catch (e) {
    estado.conectado = false;
    led("led-wifi", "azul", "parpadeo");
    ponerEstado("SIN SERVIDOR");
    serial("esp32", `No se pudo contactar el servidor (${e.name === "AbortError" ? "timeout" : e.message}). Revisa la URL y pulsa Encender de nuevo.`, "err");
    $("btn-encender").textContent = "⏻ Apagar ESP32";
  }
  actualizarBotones();
}

function apagar() {
  detenerGrabacion(true);
  detenerMicrofono();
  Object.assign(estado, { encendido: false, conectado: false, ocupado: false, inicioBoot: 0 });
  ["led-power", "led-wifi", "led-rec", "led-net"].forEach((l) => led(l, "", "off"));
  ponerEstado("APAGADO");
  $("btn-encender").textContent = "⏻ Encender ESP32";
  actualizarBotones();
}

// ------------------------------------------------------------------ grabación (pulsador)

function iniciarGrabacion() {
  if (!estado.conectado || estado.ocupado || estado.grabando || !estado.stream) return;
  estado.grabando = true;
  estado.trozos = [];
  estado.inicioGrabacion = performance.now();
  $("btn-hablar").classList.add("presionado");
  led("led-rec", "rojo");
  ponerEstado("GRABANDO");
  limpiarFlujo();
  flujo([0], "activo");
  serial("esp32", "Botón presionado → grabando por I2S...");
  estado.temporizador = setInterval(() => {
    const s = (performance.now() - estado.inicioGrabacion) / 1000;
    $("cuenta").textContent = `● ${s.toFixed(1)} s / ${estado.maxSegundos} s`;
    if (s >= estado.maxSegundos) {
      serial("esp32", `Límite de ${estado.maxSegundos} s alcanzado, se detiene la grabación.`);
      detenerGrabacion();
    }
  }, 100);
}

async function detenerGrabacion(cancelar = false) {
  if (!estado.grabando) return;
  estado.grabando = false;
  clearInterval(estado.temporizador);
  $("btn-hablar").classList.remove("presionado");
  $("nivel").style.width = "0";
  $("cuenta").textContent = "";
  led("led-rec", "", "off");
  if (cancelar) return;

  const total = estado.trozos.reduce((a, t) => a + t.length, 0);
  const crudo = new Float32Array(total);
  let o = 0;
  for (const t of estado.trozos) { crudo.set(t, o); o += t.length; }
  const duracion = total / estado.ctx.sampleRate;
  if (duracion < 0.4) {
    serial("esp32", "Pulsación muy corta, se ignora.");
    ponerEstado("LISTO");
    limpiarFlujo();
    return;
  }
  const muestras = await remuestrear(crudo, estado.ctx.sampleRate);
  const wav = crearWav(muestras);
  guardarGrabacion(wav);
  flujo([0], "hecho");
  serial("esp32", `Grabación: ${duracion.toFixed(2)} s · ${muestras.length} muestras · ${(wav.size / 1024).toFixed(1)} KB`);
  await enviar(wav);
}

async function enviarArchivo(archivo) {
  if (!archivo || !estado.conectado || estado.ocupado) return;
  try {
    const ctx = estado.ctx || new AudioContext();
    const buf = await ctx.decodeAudioData(await archivo.arrayBuffer());
    const mono = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < d.length; i++) mono[i] += d[i] / buf.numberOfChannels;
    }
    const muestras = await remuestrear(mono, buf.sampleRate);
    const wav = crearWav(muestras);
    guardarGrabacion(wav);
    limpiarFlujo();
    flujo([0], "hecho");
    serial("esp32", `Archivo "${archivo.name}": ${buf.duration.toFixed(2)} s convertido a 16 kHz mono`);
    await enviar(wav);
  } catch (e) {
    serial("esp32", `No se pudo leer el archivo: ${e.message}`, "err");
  }
}

// ------------------------------------------------------------------ envío HTTP y reproducción

const ETAPA_A_PASO = { audio_invalido: 2, grabacion_larga: 2, sin_voz: 3, stt: 3, llm: 4, tts: 5 };

async function enviar(wav) {
  const { url, token, id } = cfg();
  const falla = $("cfg-falla").value;
  $("cfg-falla").value = "";
  estado.ocupado = true;
  actualizarBotones();
  ponerEstado("ENVIANDO");
  led("led-net", "ambar", "parpadeo");
  flujo([1], "activo");
  $("txt-pregunta").textContent = "…";
  $("txt-respuesta").textContent = "…";
  $("txt-respuesta").parentElement.classList.remove("error");
  serial("esp32", `HTTP POST ${url}/api/consulta (${(wav.size / 1024).toFixed(1)} KB)${falla ? `  [falla simulada: ${falla}]` : ""}`);

  const t0 = performance.now();
  try {
    if (falla === "red") {
      await espera(1200);
      throw new TypeError("conexión rechazada (HTTPC_ERROR_CONNECTION_REFUSED)");
    }
    const cabeceras = {
      "Content-Type": "audio/wav",
      Authorization: `Bearer ${falla === "token" ? "token-incorrecto" : token}`,
      "X-Dispositivo": id,
    };
    if (["stt", "llm", "tts"].includes(falla)) cabeceras["X-Simular-Falla"] = falla;

    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 90000);
    flujo([1], "hecho");
    flujo([2, 3, 4, 5, 6], "activo");
    const r = await fetch(`${url}/api/consulta`, { method: "POST", headers: cabeceras, body: wav, signal: ctrl.signal });
    const audio = await r.blob();
    clearTimeout(t);
    const tRespuesta = performance.now() - t0;
    flujo([2, 3, 4, 5, 6], null);

    if (!(r.headers.get("Content-Type") || "").startsWith("audio/wav")) {
      let detalle = r.statusText;
      try { detalle = JSON.parse(await audio.text()).detail || detalle; } catch (_) { /* no es JSON */ }
      serial("servidor", `HTTP ${r.status}: ${detalle}`, "err");
      flujo([2], "fallo");
      serial("esp32", "Sin audio del servidor → pitido de error local.", "err");
      pitidoError();
      return terminar();
    }

    const leer = (h) => decodeURIComponent(r.headers.get(h) || "");
    const tiempos = JSON.parse(leer("X-Tiempos") || "{}");
    const error = leer("X-Error");
    const transcripcion = leer("X-Transcripcion");
    const respuesta = leer("X-Respuesta");

    if (transcripcion) serial("ia", `STT (${tiempos.stt ?? "?"} ms): "${transcripcion}"`);
    if (respuesta) serial("ia", `LLM (${tiempos.llm ?? "?"} ms): "${respuesta}"`);
    if (tiempos.tts != null) serial("ia", `TTS (${tiempos.tts} ms): ${(audio.size / 1024).toFixed(1)} KB de audio`);

    $("txt-pregunta").textContent = transcripcion || "—";
    const burbuja = $("txt-respuesta").parentElement;
    if (r.ok) {
      flujo([2, 3, 4, 5, 6], "hecho");
      burbuja.classList.remove("error");
      $("txt-respuesta").textContent = respuesta;
      serial("servidor", `HTTP 200 · turno ${leer("X-Turno")} · servidor ${tiempos.total_servidor} ms`, "ok");
    } else {
      const codigo = error.split(":")[0];
      const paso = ETAPA_A_PASO[codigo] ?? 2;
      for (let i = 2; i < paso; i++) flujo([i], "hecho");
      flujo([paso], "fallo");
      burbuja.classList.add("error");
      $("txt-respuesta").textContent = `Error (${error}). Se reproduce el mensaje de voz del servidor.`;
      serial("servidor", `HTTP ${r.status} · ${error}`, "err");
    }

    await reproducir(audio, t0, tRespuesta, tiempos, r.ok);
  } catch (e) {
    const motivo = e.name === "AbortError" ? "timeout esperando al servidor" : e.message;
    serial("esp32", `Fallo de comunicación: ${motivo}. Pitido de error local.`, "err");
    flujo([1], "fallo");
    flujo([2, 3, 4, 5, 6], null);
    $("txt-respuesta").textContent = `Sin respuesta del servidor (${motivo}).`;
    $("txt-respuesta").parentElement.classList.add("error");
    pitidoError();
  }
  terminar();
}

function reproducir(audioWav, t0, tRespuesta, tiempos, ok) {
  return new Promise((resolver) => {
    led("led-net", "", "off");
    ponerEstado("REPRODUCIENDO");
    flujo([7], "activo");
    const url = URL.createObjectURL(audioWav);
    const reproductor = new Audio(url);
    reproductor.addEventListener("playing", () => {
      const tReproduccion = performance.now() - t0;
      $("parlante").classList.add("sonando");
      serial("esp32", `Reproduciendo por I2S1 · ${Math.round(tReproduccion)} ms desde el envío hasta el inicio del audio`);
      if (ok) dibujarTiempos(tiempos, tRespuesta, tReproduccion);
    }, { once: true });
    const fin = () => {
      $("parlante").classList.remove("sonando");
      flujo([7], ok ? "hecho" : "fallo");
      URL.revokeObjectURL(url);
      resolver();
    };
    reproductor.addEventListener("ended", fin, { once: true });
    reproductor.addEventListener("error", () => {
      serial("esp32", "No se pudo reproducir el audio recibido.", "err");
      fin();
    }, { once: true });
    reproductor.play().catch(() => fin());
  });
}

function terminar() {
  estado.ocupado = false;
  led("led-net", "", "off");
  if (estado.encendido) ponerEstado(estado.conectado ? "LISTO" : "SIN SERVIDOR");
  actualizarBotones();
  actualizarRegistro();
}

function dibujarTiempos(t, tRespuesta, tReproduccion) {
  const otros = Math.max(0, tRespuesta - (t.stt || 0) - (t.llm || 0) - (t.tts || 0));
  const filas = [
    ["STT (voz → texto)", t.stt, "var(--ia)"],
    ["LLM (respuesta)", t.llm, "var(--ia)"],
    ["TTS (texto → voz)", t.tts, "var(--ia)"],
    ["Red + servidor", otros, "var(--servidor)"],
    ["Inicio reproducción", tReproduccion - tRespuesta, "var(--esp32)"],
  ];
  const max = tReproduccion || 1;
  $("barras").innerHTML = filas.map(([nombre, ms, color]) => `
    <div class="barra"><span>${nombre}</span>
      <div class="pista"><div class="relleno" style="width:${(100 * (ms || 0)) / max}%;background:${color}"></div></div>
      <span class="valor">${Math.round(ms || 0)} ms</span></div>`).join("") + `
    <div class="barra total"><span>Total hasta oír</span>
      <div class="pista"><div class="relleno" style="width:100%;background:var(--acento)"></div></div>
      <span class="valor">${(tReproduccion / 1000).toFixed(2)} s</span></div>`;
  $("nota-tiempos").textContent = "Total = desde que el ESP32 envía el audio hasta que empieza a sonar la respuesta (prueba 6 de la guía).";
}

// ------------------------------------------------------------------ registro y contexto

async function actualizarRegistro() {
  const { url, token } = cfg();
  if (!estado.conectado) return;
  try {
    const r = await fetch(`${url}/api/registro?n=15`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) return;
    const filas = (await r.json()).reverse();
    const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    $("tabla-registro").innerHTML = filas.length ? filas.map((f) => `
      <tr><td class="num">${esc(f.fecha.slice(11))}</td><td class="num">${esc(f.turno ?? "–")}</td>
      <td><span class="badge ${f.estado}">${esc(f.estado)}</span></td>
      <td>${esc(f.transcripcion)}</td><td>${esc(f.error || f.respuesta)}</td>
      <td class="num">${f.tiempos_ms.stt ?? "–"}</td><td class="num">${f.tiempos_ms.llm ?? "–"}</td>
      <td class="num">${f.tiempos_ms.tts ?? "–"}</td><td class="num">${f.tiempos_ms.total_servidor != null ? f.tiempos_ms.total_servidor + " ms" : "–"}</td></tr>`).join("")
      : `<tr><td colspan="9" class="vacio">Sin datos</td></tr>`;
  } catch (_) { /* el registro es opcional en la interfaz */ }
}

async function borrarContexto() {
  const { url, token, id } = cfg();
  try {
    const r = await fetch(`${url}/api/historial`, {
      method: "DELETE", headers: { Authorization: `Bearer ${token}`, "X-Dispositivo": id },
    });
    serial("servidor", r.ok ? "Contexto de conversación borrado." : `HTTP ${r.status} al borrar el contexto`, r.ok ? "ok" : "err");
  } catch (e) {
    serial("esp32", `No se pudo borrar el contexto: ${e.message}`, "err");
  }
}

// ------------------------------------------------------------------ eventos

function enlazar() {
  cargarConfig();
  ["cfg-ssid", "cfg-url", "cfg-token", "cfg-id"].forEach((id) => $(id).addEventListener("change", guardarConfig));
  $("btn-encender").addEventListener("click", encender);

  const boton = $("btn-hablar");
  boton.addEventListener("pointerdown", (e) => { boton.setPointerCapture(e.pointerId); iniciarGrabacion(); });
  ["pointerup", "pointercancel"].forEach((ev) => boton.addEventListener(ev, () => detenerGrabacion()));
  boton.addEventListener("contextmenu", (e) => e.preventDefault());

  const enCampo = () => ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && !enCampo()) { e.preventDefault(); iniciarGrabacion(); }
  });
  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && !enCampo()) { e.preventDefault(); detenerGrabacion(); }
  });

  $("archivo").addEventListener("change", (e) => { enviarArchivo(e.target.files[0]); e.target.value = ""; });
  $("btn-escuchar").addEventListener("click", () => {
    if (estado.ultimaGrabacion) new Audio(URL.createObjectURL(estado.ultimaGrabacion)).play();
  });
  $("btn-contexto").addEventListener("click", borrarContexto);
  $("btn-registro").addEventListener("click", actualizarRegistro);
  $("btn-limpiar").addEventListener("click", () => { $("monitor").textContent = ""; });
  actualizarBotones();
}

enlazar();
