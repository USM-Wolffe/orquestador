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
      el("p", "Sin sesión: pulsa Enter en la ventana del orquestador para entrar.", "aviso"));
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

function hace(ts) {
  if (!ts) return "";
  const segundos = Math.max(0, Math.round((Date.now() - Date.parse(ts)) / 1000));
  if (segundos < 60) return `hace ${segundos} s`;
  if (segundos < 3600) return `hace ${Math.floor(segundos / 60)} min`;
  return `hace ${Math.floor(segundos / 3600)} h`;
}

function claseAgente(agente) {
  return { cc: "ag-cc", codex: "ag-codex", cursor: "ag-cursor" }[agente] || "ag-otro";
}

function llenarSelect(select, valores, conservar) {
  const actual = conservar ? select.value : "";
  select.replaceChildren();
  for (const v of valores) {
    const o = el("option", v);
    o.value = v;
    select.append(o);
  }
  if (actual && valores.includes(actual)) select.value = actual;
}

function lista(dl, pares) {
  dl.replaceChildren();
  for (const [clave, valor] of pares) {
    dl.append(el("dt", clave), el("dd", valor === null || valor === undefined || valor === "" ? "—" : valor));
  }
}

const VEREDICTOS = { sin_reparos: "sin reparos", con_reparos: "con reparos", no_concluyente: "no concluyente" };

// --- panel lateral ---

let panel = null; // {proyecto, id, detalle, eventos, huella}

function cerrarPanel() {
  if (!panel) return;
  clearInterval(panel.detalle);
  clearInterval(panel.eventos);
  panel = null;
  const velo = $("#velo");
  velo.classList.remove("abierto");
  velo.setAttribute("aria-hidden", "true");
}

function panelGate(d, s, p, id) {
  const caja = $("#gate");
  caja.replaceChildren();
  if (d.estado !== "esperando_gate") { caja.hidden = true; return; }
  caja.hidden = false;
  caja.className = "gate";
  const nota = el("textarea");
  nota.placeholder = "Nota (obligatoria para rechazar)";
  const aprobar = el("button", "Aprobar", "btn btn-turno");
  const rechazar = el("button", "Rechazar con nota", "btn btn-sec");
  const cajaCodigo = el("div", null, "codigo");
  cajaCodigo.hidden = true;
  const etiqueta = el("label", "Escribe el código que apareció en la ventana del orquestador.");
  etiqueta.htmlFor = "cod";
  const codigo = el("input");
  codigo.id = "cod";
  codigo.inputMode = "numeric";
  codigo.maxLength = 6;
  codigo.placeholder = "······";
  const confirmar = el("button", "Confirmar aprobación", "btn btn-turno");
  const fila = el("div", null, "acciones");
  fila.append(codigo, confirmar);
  cajaCodigo.append(etiqueta, fila);
  const mensaje = el("p", "", "mensaje");
  const acciones = el("div", null, "acciones");
  acciones.append(aprobar, rechazar);
  caja.append(el("h4", "Tu decisión"), el("p", `Huella del estado revisado: ${d.gate.huella_corta}`), nota,
    acciones, cajaCodigo, mensaje);
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
    confirmar.textContent = dec === "aprobar" ? "Confirmar aprobación" : "Confirmar rechazo";
    const [estado, datos] = await enviar("preparar", { decision: dec, huella: d.gate.huella, nota: nota.value || null });
    if (estado === 200) {
      mensaje.textContent = datos.mensaje;
      cajaCodigo.hidden = false;
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

async function abrirPanel(proyecto, id) {
  const s = await sesion();
  cerrarPanel();
  const velo = $("#velo");
  velo.classList.add("abierto");
  velo.setAttribute("aria-hidden", "false");
  $("#cerrar").focus();
  const base = `/api/tareas/${encodeURIComponent(proyecto)}/${encodeURIComponent(id)}`;
  let ultimo = 0;
  let intento = null;
  let huellaMostrada;
  async function pintarDetalle() {
    const d = await api(base);
    $("#d-titulo").textContent = d.titulo || d.id;
    $("#d-sub").textContent = `${d.cambio} · ${d.nombre_agente || d.agente} · ${d.estado_texto || ""}`;
    $("#d-explicacion").textContent = d.explicacion || "Sin explicación de lo que se aprueba.";
    $("#d-revision").textContent = d.revision
      ? `${VEREDICTOS[d.revision.veredicto] || d.revision.veredicto}. ${d.revision.resumen || ""}` : "Sin revisión";
    const diff = $("#d-diff");
    const vacio = $("#d-diff-vacio");
    if (!d.diff_disponible) { diff.replaceChildren(); vacio.hidden = false; }
    else {
      vacio.hidden = true;
      const filas = [];
      for (const a of d.diffstat.archivos) {
        const tr = el("tr");
        const tdRuta = el("td", `${a.ruta}${a.nuevo ? " (nuevo)" : ""}`);
        const tdCambio = el("td");
        const mas = el("span", `+${a.agregadas ?? "?"}`, "mas");
        const menos = el("span", `−${a.borradas ?? "?"}`, "menos");
        tdCambio.append(mas, document.createTextNode(" "), menos);
        tr.append(tdRuta, tdCambio);
        filas.push(tr);
      }
      diff.replaceChildren(...filas);
    }
    $("#informe").textContent = d.informe || "sin informe";
    const r = d.resultado || {};
    lista($("#resultado"), [["Ok", r.ok], ["Error", r.error ? `${r.error.clase}: ${r.error.mensaje}` : null],
      ["Duración (s)", r.duracion_s]]);
    lista($("#campos"), [["Id", d.id], ["Proyecto", d.proyecto], ["Estado", d.estado], ["Motivo", d.motivo],
      ["Agente", d.agente], ["Cambio", d.cambio], ["Rama", d.rama], ["Intentos", `${d.intentos}/${d.max_intentos}`],
      ["Dependencias", (d.dependencias || []).join(", ")], ["Plan agotado hasta", d.plan_agotado_hasta],
      ["Prompt", d.prompt]]);
    lista($("#niveles"), Object.entries(d.niveles || {}));
    lista($("#consumo"), Object.entries(d.consumo || {}).map(([a, c]) => [a, JSON.stringify(c)]));
    $("#historial").replaceChildren(...d.historial.map((h) => el("li",
      `${h.en} · ${h.de || "—"} → ${h.a} · ${h.por}${h.via ? " (" + h.via + ")" : ""} · ${h.motivo || ""}`)));
    const clave = `${d.estado}|${d.gate.huella}`;
    if (clave !== huellaMostrada) {
      huellaMostrada = clave;
      panelGate(d, s, proyecto, id);
    }
  }
  async function pintarEventos() {
    const d = await api(`${base}/eventos?desde=0`);
    intento = d.intento;
    ultimo = d.ultimo;
    const ahoraLi = (d.frases || []).map((f, i, arr) => {
      const li = el("li", null, i === arr.length - 1 ? "ahora" : "");
      li.append(el("time", (f.ts || "").slice(11, 16)), document.createTextNode(f.frase));
      return li;
    });
    $("#d-bitacora").replaceChildren(...ahoraLi);
  }
  await pintarDetalle();
  await pintarEventos();
  panel = { proyecto, id, detalle: setInterval(pintarDetalle, 3000), eventos: setInterval(pintarEventos, 1500) };
}

// --- página principal ---

async function tablero() {
  const s = await sesion();
  const select = $("#f-proyecto");
  llenarSelect(select, s.proyectos, false);
  if (!panel) {
    $("#cerrar").onclick = cerrarPanel;
    $("#velo").addEventListener("click", (e) => { if (e.target === $("#velo")) cerrarPanel(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarPanel(); });
  }
  async function pintar() {
    const proyecto = select.value || s.proyectos[0] || "";
    const d = await api(`/api/tablero?proyecto=${encodeURIComponent(proyecto)}`);
    $("#vivo").textContent = d.momento ? `Funcionando · revisado ${hace(d.momento)}` : "Funcionando";
    // Te toca decidir
    const n = d.turno.length;
    $("#turno-sub").textContent = n === 0 ? "" : (n === 1
      ? "1 tarea terminó y espera tu aprobación. Nada avanza en ese cambio hasta que decidas."
      : `${n} tareas terminaron y esperan tu aprobación. Nada avanza en esos cambios hasta que decidas.`);
    if (!d.turno.length) {
      $("#turno").replaceChildren(el("p", "Nada que decidir ahora"));
    } else {
      const decisiones = d.turno.map((g) => {
        const caja = el("div", null, "decision");
        const texto = el("div");
        texto.append(el("h3", g.titulo));
        if (g.explicacion) texto.append(el("p", g.explicacion));
        const evidencia = el("div", null, "evidencia");
        const archivos = el("span");
        archivos.append(el("b", g.archivos), document.createTextNode(" archivos cambiados"));
        evidencia.append(archivos);
        if (g.pruebas) evidencia.append(el("span", g.pruebas.ok ? "Pruebas en verde" : "Pruebas: fallaron"));
        const revision = el("span");
        if (g.revision) {
          revision.append(document.createTextNode("Revisión: "),
            el("b", VEREDICTOS[g.revision.veredicto] || g.revision.veredicto));
        } else revision.textContent = "Sin revisión";
        evidencia.append(revision);
        texto.append(evidencia);
        const boton = el("button", "Revisar y decidir", "btn btn-turno");
        boton.onclick = () => abrirPanel(g.proyecto || proyecto, g.id);
        caja.append(texto, boton);
        return caja;
      });
      $("#turno").replaceChildren(...decisiones);
    }
    // Ahora mismo
    const filas = d.agentes.map((a) => {
      const fila = el("div", null, a.estado === "apagado" ? "agente apagado" : "agente");
      const quien = el("div", null, "quien");
      quien.append(el("span", null, `ficha ${claseAgente(a.agente)}`), document.createTextNode(a.nombre));
      const que = el("div", null, "que");
      const titulo = a.estado === "trabajando" ? a.tarea : (a.estado === "plan_agotado" ? "Plan agotado" : (a.estado === "apagado" ? "Apagado" : "Disponible"));
      que.append(el("b", titulo || "Disponible"));
      const detalle = a.frase ? `${a.frase} · ${hace(a.frase_en)}` : (a.motivo || "");
      que.append(el("span", detalle));
      const medidor = el("div", null, "medidor");
      if (a.plan && a.plan.uso !== null && a.plan.uso !== undefined) {
        medidor.append(document.createTextNode(
          `Plan: ${Math.round(a.plan.uso * 100)} % usado · según Claude Code, ${hace(a.plan.visto_en)}`));
        const meter = document.createElement("meter");
        meter.min = "0"; meter.max = "1"; meter.value = String(a.plan.uso);
        medidor.append(meter);
      } else {
        medidor.textContent = `${a.hoy.minutos} min de trabajo · ${a.hoy.tareas} tareas hoy`;
      }
      fila.append(quien, que, medidor);
      return fila;
    });
    $("#agentes").replaceChildren(...filas);
    // El plan
    const lineas = d.plan.map((linea) => {
      const caja = el("div", null, "linea");
      const header = el("header");
      header.append(el("h3", linea.cambio),
        el("span", `${linea.listas} de ${linea.total} listas${linea.nota ? " · " + linea.nota : ""}`));
      const via = el("div", null, "via");
      for (const e of linea.estaciones) {
        const boton = el("button", null, `estacion ${e.forma} ${claseAgente(e.agente)}`);
        boton.type = "button";
        const punto = el("span", e.forma === "hecha" ? "✓" : (e.forma === "espera" ? "!" : ""), "punto");
        boton.append(punto, el("b", e.titulo), el("small", e.texto));
        boton.onclick = () => abrirPanel(linea.proyecto || proyecto, e.id);
        via.append(boton);
      }
      caja.append(header, via);
      return caja;
    });
    $("#plan").replaceChildren(...lineas);
  }
  select.onchange = pintar;
  await pintar();
  setInterval(pintar, 3000);
}

// --- consumo ---

async function consumo() {
  const s = await sesion();
  llenarSelect($("#f-proyecto"), ["", ...s.proyectos], false);
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

const PAGINAS = { tablero, consumo };
document.addEventListener("DOMContentLoaded", () => {
  const pagina = PAGINAS[document.body.dataset.pagina];
  if (pagina) pagina().catch(() => {});
});
