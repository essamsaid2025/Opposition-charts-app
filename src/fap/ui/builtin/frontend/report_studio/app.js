/* Report Studio v2 — Phase A architecture proof.
 *
 * React shell (chrome/state/lifecycle) + Konva rendering engine (canvas).
 * The persisted model is an ENGINE-INDEPENDENT document: pages[] -> elements[]
 * with stable ids and plain geometry (x,y,width,height,rotation) + type-specific
 * props. Konva never dictates the document format — nodes are built FROM the
 * document and geometry is read BACK into it. No Konva scene JSON is persisted.
 */
(function () {
  "use strict";
  var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
  var html = htm.bind(React.createElement);

  // ---------------------------------------------------------------- bridge
  function send(type, extra) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type: type }, extra || {}), "*");
  }
  function ready() { send("streamlit:componentReady", { apiVersion: 1 }); }
  function setHeight(h) { send("streamlit:setFrameHeight", { height: (h || document.body.scrollHeight) + 4 }); }
  var lastTs = 0;
  function nextTs() { var t = Date.now(); if (t <= lastTs) t = lastTs + 1; lastTs = t; return t; }
  function emitDoc(doc) {
    send("streamlit:setComponentValue", { dataType: "json", value: { ts: nextTs(), document: doc } });
  }

  // ---------------------------------------------------------------- doc helpers
  function uid(p) { return (p || "el") + "-" + Math.random().toString(36).slice(2, 9); }
  function activePage(doc) {
    var pages = doc.pages || [];
    return pages.filter(function (p) { return p.id === doc.active_page; })[0] || pages[0];
  }
  function demoDoc() {
    var pid = uid("page");
    return {
      schema_version: 1, id: uid("doc"), title: "Untitled report",
      theme: { background: "#ffffff", accent: "#2f7bd6" },
      metadata: {}, active_page: pid,
      pages: [{
        id: pid, name: "Page 1", width: 794, height: 1123, background: "#ffffff",
        elements: [
          { id: uid("rect"), type: "rect", x: 80, y: 90, width: 300, height: 160,
            rotation: 0, fill: "#eaf2fb", stroke: "#2f7bd6" },
          { id: uid("text"), type: "text", x: 80, y: 300, width: 420, rotation: 0,
            text: "Text placeholder", fontSize: 28, fill: "#1b2430" }
        ]
      }]
    };
  }

  // ---------------------------------------------------------------- Konva editor
  // Imperative controller: owns the Stage/Layer/Transformer and element nodes,
  // keeps the passed-in `doc` in sync, and calls onCommit(doc) after any edit.
  function createEditor(container, doc, cb) {
    var page = activePage(doc);
    var stage = new Konva.Stage({ container: container, width: page.width, height: page.height });
    var layer = new Konva.Layer();
    stage.add(layer);
    // page background
    var bg = new Konva.Rect({ x: 0, y: 0, width: page.width, height: page.height,
      fill: page.background || "#ffffff", listening: true, name: "bg" });
    layer.add(bg);
    var tr = new Konva.Transformer({ rotateEnabled: true, ignoreStroke: true,
      boundBoxFunc: function (o, n) { return (n.width < 24 || n.height < 24) ? o : n; } });
    layer.add(tr);

    var nodes = {};                              // element id -> Konva node

    function select(id) {
      tr.nodes(id && nodes[id] ? [nodes[id]] : []);
      layer.batchDraw();
      cb.onSelect && cb.onSelect(id || null);
    }
    function commit() { cb.onCommit && cb.onCommit(doc); }
    function elem(id) {
      var els = page.elements; for (var i = 0; i < els.length; i++) if (els[i].id === id) return els[i];
      return null;
    }

    function wire(node, id) {
      node.on("mousedown touchstart", function (e) { e.cancelBubble = true; select(id); });
      node.on("dragend", function () {
        var el = elem(id); if (!el) return;
        el.x = Math.round(node.x()); el.y = Math.round(node.y()); commit();
      });
      node.on("transformend", function () {
        var el = elem(id); if (!el) return;
        el.x = Math.round(node.x()); el.y = Math.round(node.y());
        el.rotation = Math.round(node.rotation());
        if (el.type === "rect") {
          el.width = Math.round(node.width() * node.scaleX());
          el.height = Math.round(node.height() * node.scaleY());
        } else {                                  // text: width scales, fontSize scales
          el.width = Math.round(node.width() * node.scaleX());
          el.fontSize = Math.max(6, Math.round((el.fontSize || 20) * node.scaleY()));
          node.fontSize(el.fontSize); node.width(el.width);
        }
        node.scaleX(1); node.scaleY(1); layer.batchDraw(); commit();
      });
    }

    function makeNode(el) {
      var node;
      if (el.type === "text") {
        node = new Konva.Text({ x: el.x, y: el.y, width: el.width || 300, text: el.text || "",
          fontSize: el.fontSize || 20, fill: el.fill || "#1b2430", rotation: el.rotation || 0,
          draggable: true });
      } else {                                    // rect (default)
        node = new Konva.Rect({ x: el.x, y: el.y, width: el.width || 120, height: el.height || 80,
          fill: el.fill || "#eaf2fb", stroke: el.stroke || "#2f7bd6", strokeWidth: 1.5,
          cornerRadius: 4, rotation: el.rotation || 0, draggable: true });
      }
      nodes[el.id] = node; layer.add(node); wire(node, el.id);
      return node;
    }

    function buildAll() {
      Object.keys(nodes).forEach(function (id) { nodes[id].destroy(); });
      nodes = {};
      (page.elements || []).forEach(makeNode);
      tr.moveToTop();
      layer.draw();
    }
    buildAll();

    // click empty background clears selection
    bg.on("mousedown touchstart", function () { select(null); });

    return {
      addRect: function () {
        var el = { id: uid("rect"), type: "rect", x: 120, y: 120, width: 200, height: 120,
          rotation: 0, fill: "#eaf2fb", stroke: "#2f7bd6" };
        page.elements.push(el); makeNode(el); tr.moveToTop(); layer.draw(); select(el.id); commit();
      },
      addText: function () {
        var el = { id: uid("text"), type: "text", x: 120, y: 120, width: 320, rotation: 0,
          text: "Text placeholder", fontSize: 24, fill: "#1b2430" };
        page.elements.push(el); makeNode(el); tr.moveToTop(); layer.draw(); select(el.id); commit();
      },
      deleteSelected: function () {
        var ns = tr.nodes(); if (!ns.length) return;
        var id = Object.keys(nodes).filter(function (k) { return nodes[k] === ns[0]; })[0];
        if (!id) return;
        nodes[id].destroy(); delete nodes[id];
        page.elements = page.elements.filter(function (e) { return e.id !== id; });
        select(null); layer.draw(); commit();
      },
      count: function () { return (page.elements || []).length; },
      doc: function () { return doc; },
      height: function () { return page.height; },
      destroy: function () { try { stage.destroy(); } catch (e) {} }
    };
  }

  // ---------------------------------------------------------------- React shell
  function App(props) {
    var st = useState(props.doc);
    var doc = st[0], setDoc = st[1];
    var savedState = useState(true); var saved = savedState[0], setSaved = savedState[1];
    var countState = useState(0); var count = countState[0], setCount = countState[1];
    var containerRef = useRef(null);
    var editorRef = useRef(null);

    useEffect(function () {
      if (!containerRef.current) return;
      var ed = createEditor(containerRef.current, doc, {
        onCommit: function (d) { setSaved(false); setCount(ed.count()); emitDoc(d); setTimeout(function () { setSaved(true); }, 200); },
        onSelect: function () {}
      });
      editorRef.current = ed;
      setCount(ed.count());
      setHeight(ed.height() + 90);
      return function () { ed.destroy(); };
      // eslint-disable-next-line
    }, []);

    function onTitle(e) {
      var d = editorRef.current ? editorRef.current.doc() : doc;
      d.title = e.target.value; setDoc(Object.assign({}, d)); setSaved(false); emitDoc(d);
      setTimeout(function () { setSaved(true); }, 200);
    }

    return html`
      <div>
        <div class="rs-toolbar">
          <input class="rs-title" value=${doc.title || ""} onInput=${onTitle} aria-label="Report name" />
          <button class="rs-btn" onClick=${function () { editorRef.current && editorRef.current.addRect(); }}>+ Rectangle</button>
          <button class="rs-btn" onClick=${function () { editorRef.current && editorRef.current.addText(); }}>+ Text</button>
          <button class="rs-btn" onClick=${function () { editorRef.current && editorRef.current.deleteSelected(); }}>Delete</button>
          <span class="rs-spacer"></span>
          <span class="rs-status">${count} element${count === 1 ? "" : "s"} · ${saved ? "saved" : "saving…"}</span>
        </div>
        <div class="rs-stage-wrap"><div ref=${containerRef}></div></div>
        <div class="rs-hint">Phase A proof — Konva engine · click to select · drag to move · handles to resize/rotate · autosaves to the report document.</div>
      </div>`;
  }

  // ---------------------------------------------------------------- mount + wiring
  var rootEl = document.getElementById("root");
  var reactRoot = null, mounted = false;
  function mount(doc) {
    mounted = true;
    // stable-ish: (re)mount fresh so the editor rebuilds from the given document
    if (reactRoot && ReactDOM.createRoot) { reactRoot.unmount(); }
    if (ReactDOM.createRoot) {
      reactRoot = ReactDOM.createRoot(rootEl);
      reactRoot.render(html`<${App} doc=${doc} key=${doc.id + "|" + (doc.active_page || "")} />`);
    } else {
      ReactDOM.render(html`<${App} doc=${doc} />`, rootEl);
    }
    setTimeout(function () { setHeight(); }, 50);
  }

  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.type !== "streamlit:render") return;
    var args = data.args || {};
    if (args.document && args.document.pages) { mount(args.document); }
  });
  window.addEventListener("resize", function () { setHeight(); });
  if (window.ResizeObserver) { new ResizeObserver(function () { setHeight(); }).observe(document.body); }

  ready();
  // dev fallback: opened standalone (no Streamlit host) -> show a demo so the
  // canvas can be verified in a plain browser. Harmless inside Streamlit (a real
  // render arrives first and sets `mounted`).
  setTimeout(function () { if (!mounted) mount(demoDoc()); }, 700);
})();
