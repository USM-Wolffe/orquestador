"use strict";
// Tablero del orquestador: solo lectura salvo el gate por botón. Sin bibliotecas externas ni HTML armado con
// datos: todo se pinta con textContent.

const $ = (selector) => document.querySelector(selector);

function el(etiqueta, texto, clase) {
  const e = document.createElement(etiqueta);
  if (texto !== undefined && texto !== null) e.textContent = String(texto);
  if (clase) e.className = clase;
  return e;
}

async function api(ruta) {
  const r = await fetch(ruta, { credentials: "same-origin" });
  if (r.status === 401) {
    document.querySelector("main").replaceChildren(
      el("p", "Sin sesión: abre el enlace que muestra la terminal de orq correr.", "aviso"));
    throw new Error("sin sesión");
  }
  return r.json();
}

let SESION = null;
async function sesion() {
  if (!SESION) SESION = await api("/api/sesion");
  const aviso = $("#aviso");
  const texto = SESION.gates.deshabilitados || SESION.gates.aviso_integridad;
  if (aviso && texto) { aviso.textContent = texto; aviso.hidden = false; }
  return SESION;
}

function duracion(segundos) {
  if (segundos === null || segundos === undefined) return "";
  if (segundos < 60) return `${segundos} s`;
  if (segundos < 3600) return `${Math.floor(segundos / 60)} min`;
  return `${Math.floor(segundos / 3600)} h ${Math.floor((segundos % 3600) / 60)} min`;
}

function llenarSelect(select, valores) {
  for (const v of valores) {
    const o = el("option", v);
    o.value = v;
    select.append(o);
  }
}

function lista(dl, pares) {
  dl.replaceChildren();
  for (const [clave, valor] of pares) {
    dl.append(el("dt", clave), el("dd", valor === null || valor === undefined ? "—" : valor));
  }
}

// --- kanban ---

function tarjeta(c) {
  const a = el("a", null, "tarjeta");
  a.href = `/detalle?p=${encodeURIComponent(c.proyecto)}&id=${encodeURIComponent(c.id)}`;
  a.append(el("strong", c.id), el("span", c.titulo, "titulo"),
    el("small", `${c.proyecto} · ${c.cambio} · ${c.agente}`),
    el("small", `intentos ${c.intentos}/${c.max_intentos} · ${duracion(c.segundos_en_estado)} en este estado`));
  if (c.plan_agotado_hasta) a.append(el("small", `${c.agente}: plan agotado hasta ${c.plan_agotado_hasta}`, "aviso"));
  else if (c.motivo) a.append(el("small", c.motivo, "motivo"));
  if (c.gate && c.gate.huella_corta && c.estado === "esperando_gate") a.append(el("small", `huella ${c.gate.huella_corta}`));
  return a;
}

async function kanban() {
  const s = await sesion();
  llenarSelect($("#f-proyecto"), s.proyectos);
  llenarSelect($("#f-agente"), s.agentes);
  async function pintar() {
    const q = new URLSearchParams();
    if ($("#f-proyecto").value) q.set("proyecto", $("#f-proyecto").value);
    if ($("#f-agente").value) q.set("agente", $("#f-agente").value);
    const d = await api(`/api/tareas?${q}`);
    const columnas = [];
    for (const estado of d.estados) {
      const col = el("section", null, "columna");
      col.append(el("h2", estado));
      for (const c of d.tarjetas.filter((x) => x.estado === estado)) col.append(tarjeta(c));
      columnas.push(col);
    }
    $("#kanban").replaceChildren(...columnas);
  }
  $("#f-proyecto").onchange = pintar;
  $("#f-agente").onchange = pintar;
  await pintar();
  setInterval(pintar, 3000);
}

// --- detalle ---

function lineaEvento(e) {
  const d = e.datos || {};
  let texto;
  if (e.tipo === "archivo") texto = `${d.accion} ${d.ruta}`;
  else if (e.tipo === "comando") texto = `$ ${d.comando} (${d.estado || ""})`;
  else if (e.tipo === "herramienta") texto = `${d.nombre} ${d.objetivo || ""} (${d.estado || ""})`;
  else if (e.tipo === "mensaje") texto = d.texto;
  else if (e.tipo === "error") texto = `${d.clase}: ${d.mensaje || ""}`;
  else texto = JSON.stringify(d);
  return el("li", `${e.ts} · ${e.tipo} · ${texto}`);
}

function panelGate(d, s, p, id) {
  const caja = $("#gate");
  if (d.estado !== "esperando_gate") { caja.hidden = true; caja.replaceChildren(); return; }
  caja.hidden = false;
  const nota = el("textarea");
  nota.placeholder = "Nota (obligatoria para rechazar)";
  const aprobar = el("button", "Aprobar");
  const rechazar = el("button", "Rechazar con nota");
  const codigo = el("input");
  codigo.inputMode = "numeric";
  codigo.maxLength = 6;
  codigo.placeholder = "Código de 6 dígitos de la terminal";
  codigo.hidden = true;
  const confirmar = el("button", "Confirmar");
  confirmar.hidden = true;
  const mensaje = el("p", "", "mensaje");
  caja.replaceChildren(el("h2", "Gate"), el("p", `Huella del estado revisado: ${d.gate.huella_corta}`), nota,
    aprobar, rechazar, codigo, confirmar, mensaje);
  if (s.gates.deshabilitados) {
    aprobar.disabled = rechazar.disabled = true;
    mensaje.textContent = s.gates.deshabilitados;
  }
  let decision = null;
  async function enviar(paso, cuerpo) {
    const r = await fetch(`/api/gate/${encodeURIComponent(p)}/${encodeURIComponent(id)}/${paso}`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Orq-CSRF": s.csrf },
      body: JSON.stringify(cuerpo),
    });
    return [r.status, await r.json()];
  }
  function bloquear(texto) {
    aprobar.disabled = rechazar.disabled = confirmar.disabled = true;
    mensaje.textContent = texto;
  }
  async function preparar(dec) {
    decision = dec;
    const [estado, datos] = await enviar("preparar", { decision: dec, huella: d.gate.huella, nota: nota.value || null });
    if (estado === 200) {
      mensaje.textContent = datos.mensaje;
      codigo.hidden = confirmar.hidden = false;
      codigo.value = "";
      codigo.focus();
    } else if (estado === 423) bloquear(datos.error);
    else mensaje.textContent = datos.error;
  }
  aprobar.onclick = () => preparar("aprobar");
  rechazar.onclick = () => preparar("rechazar");
  confirmar.onclick = async () => {
    const [estado, datos] = await enviar("confirmar",
      { decision, huella: d.gate.huella, nota: nota.value || null, codigo: codigo.value });
    if (estado === 200) bloquear(`Decisión aplicada: ${datos.decision}`);
    else if (estado === 423) bloquear(datos.error);
    else mensaje.textContent = datos.error;
  };
}

async function detalle() {
  const s = await sesion();
  const q = new URLSearchParams(location.search);
  const p = q.get("p");
  const id = q.get("id");
  const base = `/api/tareas/${encodeURIComponent(p)}/${encodeURIComponent(id)}`;
  let ultimo = 0;
  let intento = null;
  let huellaMostrada;
  async function pintarDetalle() {
    const d = await api(base);
    $("#titulo").textContent = `${d.id} · ${d.titulo} (${d.estado})`;
    lista($("#campos"), [["Proyecto", d.proyecto], ["Estado", d.estado], ["Motivo", d.motivo], ["Agente", d.agente],
      ["Cambio", d.cambio], ["Rama", d.rama], ["Intentos", `${d.intentos}/${d.max_intentos}`],
      ["Dependencias", (d.dependencias || []).join(", ")], ["Plan agotado hasta", d.plan_agotado_hasta],
      ["Prompt", d.prompt]]);
    lista($("#niveles"), Object.entries(d.niveles || {}));
    const diff = $("#diff");
    if (!d.diff_disponible) diff.replaceChildren(el("p", "diff no disponible"));
    else {
      const ul = el("ul");
      for (const a of d.diffstat.archivos) {
        ul.append(el("li", `${a.ruta}${a.nuevo ? " (nuevo)" : ""}: +${a.agregadas ?? "?"} −${a.borradas ?? "?"}`));
      }
      diff.replaceChildren(ul);
    }
    $("#informe").textContent = d.informe || "sin informe";
    const r = d.resultado || {};
    lista($("#resultado"), [["Ok", r.ok], ["Error", r.error ? `${r.error.clase}: ${r.error.mensaje}` : null],
      ["Duración (s)", r.duracion_s]]);
    lista($("#consumo"), Object.entries(d.consumo || {}).map(([a, c]) => [a, JSON.stringify(c)]));
    const hist = $("#historial");
    hist.replaceChildren(...d.historial.map((h) => el("li",
      `${h.en} · ${h.de || "—"} → ${h.a} · ${h.por}${h.via ? " (" + h.via + ")" : ""} · ${h.motivo || ""}`)));
    const clave = `${d.estado}|${d.gate.huella}`;
    if (clave !== huellaMostrada) {
      huellaMostrada = clave;
      panelGate(d, s, p, id);
    }
  }
  async function pintarEventos() {
    const d = await api(`${base}/eventos?desde=${ultimo}`);
    if (intento !== d.intento) {
      intento = d.intento;
      $("#actividad").replaceChildren();
    }
    for (const e of d.eventos) $("#actividad").append(lineaEvento(e));
    ultimo = d.ultimo;
  }
  await pintarDetalle();
  await pintarEventos();
  setInterval(pintarEventos, 1500);
  setInterval(pintarDetalle, 3000);
}

// --- consumo ---

async function consumo() {
  const s = await sesion();
  llenarSelect($("#f-proyecto"), s.proyectos);
  async function pintar() {
    const q = new URLSearchParams();
    for (const [campo, nombre] of [["#f-proyecto", "proyecto"], ["#f-desde", "desde"], ["#f-hasta", "hasta"]]) {
      if ($(campo).value) q.set(nombre, $(campo).value);
    }
    const d = await api(`/api/consumo?${q}`);
    const filas = d.agentes.map((a) => {
      const tr = el("tr");
      for (const v of [a.agente, a.tareas, a.intentos, duracion(Math.round(a.segundos)), a.tokens_entrada,
        a.tokens_salida, a.tokens_cache_lectura, a.tokens_cache_escritura, a.costo_texto, a.limites,
        a.proximo_reinicio || "—"]) tr.append(el("td", v));
      return tr;
    });
    $("#tabla-consumo tbody").replaceChildren(...filas);
  }
  for (const campo of ["#f-proyecto", "#f-desde", "#f-hasta"]) $(campo).onchange = pintar;
  await pintar();
}

const PAGINAS = { kanban, detalle, consumo };
document.addEventListener("DOMContentLoaded", () => {
  const pagina = PAGINAS[document.body.dataset.pagina];
  if (pagina) pagina().catch(() => {});
});
