<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8" />
<title>Chatbot Intranet</title>

<meta name="viewport" content="width=device-width, initial-scale=1.0">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap" rel="stylesheet">

<style>
/* ===== BASE ===== */
body{
  margin:0;
  font-family:'Inter', system-ui, -apple-system, sans-serif;
  background:#f2f4f8;
}

/* ===== LAYOUT ===== */
#layout{
  display:grid;
  grid-template-columns: 38% 62%;
  gap:18px;
  padding:18px;
  height:100vh;
  box-sizing:border-box;
}

/* ===== PANELS / CARDS ===== */
.panel{
  background:#ffffff;
  border-radius:16px;
  padding:14px;
  box-shadow:
    0 10px 30px rgba(0,0,0,.08),
    0 1px 4px rgba(0,0,0,.06);
  display:flex;
  flex-direction:column;
  min-height:0;
}

.panel h3{
  margin:4px 0 10px 0;
  font-weight:600;
  font-size:15px;
  color:#111;
}

/* ===== BUSCADOR ===== */
#searchBox{
  display:flex;
  gap:6px;
  flex-wrap:wrap;
}

#searchBox input, #searchBox select{
  padding:8px 10px;
  border-radius:8px;
  border:1px solid #ddd;
  outline:none;
  font-size:13px;
}

#searchBox input:focus, #searchBox select:focus{
  border-color:#4f46e5;
  box-shadow:0 0 0 2px rgba(79,70,229,.15);
}

button{
  background:#4f46e5;
  color:white;
  border:none;
  border-radius:8px;
  padding:8px 14px;
  cursor:pointer;
  font-weight:500;
  font-size:13px;
}

button:hover{ background:#4338ca; }

#results{
  margin-top:12px;
  overflow-y:auto;
  flex:1;
  padding-right:4px;
}

#results hr{
  border:none;
  border-top:1px solid #eee;
  margin:10px 0;
}

#results b{ font-size:13px; }
#results small{ color:#666; }

mark{
  background:#fde68a;
  padding:0 2px;
  border-radius:3px;
}

/* ===== CHAT ===== */
#chat{
  flex:1;
  padding:10px;
  overflow-y:auto;
  background:#f8fafc;
  border-radius:12px;
  display:flex;
  flex-direction:column;
}

.user{
  align-self:flex-end;
  background:#4f46e5;
  color:white;
  padding:8px 12px;
  border-radius:14px 14px 4px 14px;
  margin:6px 0;
  max-width:80%;
  font-size:13px;
}

.bot{
  align-self:flex-start;
  background:#eef2f7;
  color:#111;
  padding:10px 12px;
  border-radius:14px 14px 14px 4px;
  margin:6px 0 12px 0;
  max-width:85%;
  font-size:13px;
}

.bot button{
  margin-top:6px;
  font-size:11px;
  padding:5px 8px;
}

/* ===== INPUT BAR ===== */
.inputBar{
  display:flex;
  gap:8px;
  margin-top:10px;
}

.inputBar input{
  flex:1;
  padding:10px 12px;
  border-radius:10px;
  border:1px solid #ddd;
  font-size:13px;
}

/* ===== TYPING ===== */
#typing{
  font-style:italic;
  color:#777;
  font-size:12px;
  margin:4px 0;
}

/* ===== FEEDBACK ===== */
.star{ cursor:pointer; font-size:16px; color:#ccc }
.star.selected{ color:gold }

.feedbackBox{
  margin-top:6px;
  background:#f1f5f9;
  padding:6px;
  border-radius:8px
}

/* =========================
   📱 MOBILE RESPONSIVE
========================= */
@media (max-width: 900px){

  #layout{
    grid-template-columns: 1fr;
    grid-template-rows: 1fr auto;
    height:100vh;
  }

  .panel{
    border-radius:14px;
  }

  /* chat arriba */
  .panel:nth-child(2){
    order:1;
  }

  /* buscador abajo */
  .panel:nth-child(1){
    order:2;
    max-height:40vh;
  }

  #results{
    max-height:30vh;
  }

  .inputBar input{
    font-size:16px; /* evita zoom iOS */
  }

  button{
    padding:10px 14px;
  }
}
</style>
</head>

<body>

<div id="layout">

  <!-- ================= BUSCADOR ================= -->
  <div class="panel">

    <h3>🔍 Buscador de notas</h3>

    <div id="searchBox">
      <input id="searchText" placeholder="Buscar por palabra…" style="width:60%">
      <select id="yearFilter"><option value="">Todos los años</option></select>
      <button onclick="runSearch()">Buscar</button>
    </div>

    <div id="results"></div>

  </div>

  <!-- ================= CHAT ================= -->
  <div class="panel">

    <h3>💬 Chat Intranet</h3>

    <div id="chat"></div>
    <div id="typing" style="display:none;">🤖 Escribiendo…</div>

    <div class="inputBar">
      <input id="msg" placeholder="Escribí tu pregunta…" />
      <button onclick="send()">Enviar</button>
    </div>

  </div>

</div>

<script>
const chat = document.getElementById("chat");
const input = document.getElementById("msg");
const typing = document.getElementById("typing");
const resultsBox = document.getElementById("results");
const yearFilter = document.getElementById("yearFilter");

let ALL_DATA = [];

/* ================= LOAD DATA ================= */
fetch("/data")
.then(r=>r.json())
.then(data=>{
  ALL_DATA = data;
  const years = [...new Set(data.map(d=>d.anio).filter(Boolean))].sort((a,b)=>b-a);
  years.forEach(y=>{
    const opt=document.createElement("option");
    opt.value=y;
    opt.textContent=y;
    yearFilter.appendChild(opt);
  });
});

/* ================= HELPERS ================= */
function previewText(txt){
  if(!txt) return "";
  return txt.replace(/\s+/g," ").slice(0,220)+"...";
}

function highlight(text,q){
  if(!q) return text;
  const re=new RegExp(`(${q})`,"gi");
  return text.replace(re,"<mark>$1</mark>");
}

/* ================= SEARCH ================= */
function runSearch(){
  const q=document.getElementById("searchText").value.toLowerCase().trim();
  const year=yearFilter.value;
  resultsBox.innerHTML="";

  if(!q){
    resultsBox.innerHTML="<i>Escribí una palabra para buscar</i>";
    return;
  }

  let res=ALL_DATA.filter(d=>{
    if(year && String(d.anio)!==year) return false;
    const text=(d.titulo+" "+d.texto).toLowerCase();
    return text.includes(q);
  });

  res.sort((a,b)=>{
    if(!a.fecha_iso || !b.fecha_iso) return 0;
    return b.fecha_iso.localeCompare(a.fecha_iso);
  });

  if(!res.length){
    resultsBox.innerHTML="<i>No hay resultados</i>";
    return;
  }

  res.slice(0,80).forEach(d=>{
    const div=document.createElement("div");
    const title=highlight(d.titulo||"",q);
    const prev=highlight(previewText(d.texto||""),q);

    div.innerHTML=`
      <b>${title}</b><br>
      <small>${d.fecha||""}</small><br>
      <div style="color:#555;font-size:12px;margin:4px 0">${prev}</div>
      <a href="${d.url}" target="_blank">Abrir nota</a>
      <hr>
    `;
    resultsBox.appendChild(div);
  });

  input.focus();
}

/* ================= CHAT UI ================= */
function addUser(text){
  const d=document.createElement("div");
  d.className="user";
  d.textContent=text;
  chat.appendChild(d);
  chat.scrollTop=chat.scrollHeight;
}

function addBot(html,question){
  const wrap=document.createElement("div");
  wrap.className="bot";

  const content=document.createElement("div");
  content.innerHTML=html;

  const copyBtn=document.createElement("button");
  copyBtn.textContent="📋 Copiar";
  copyBtn.onclick=()=>copyFormatted(content);

  const fbBox=buildFeedback(question,content.innerText);

  wrap.appendChild(content);
  wrap.appendChild(copyBtn);
  wrap.appendChild(fbBox);
  chat.appendChild(wrap);
  chat.scrollTop=chat.scrollHeight;
}

/* ================= COPY ================= */
function copyFormatted(el){
  const clone=el.cloneNode(true);
  clone.querySelectorAll("a").forEach(a=>{
    a.replaceWith(`${a.textContent}: ${a.href}`);
  });
  const txt=clone.innerText.trim();
  navigator.clipboard.writeText(txt).then(()=>alert("Copiado"));
}

/* ================= FEEDBACK ================= */
function buildFeedback(question,answer){
  const box=document.createElement("div");
  box.className="feedbackBox";
  let rating=0;

  const stars=document.createElement("div");
  for(let i=1;i<=5;i++){
    const s=document.createElement("span");
    s.textContent="★";
    s.className="star";
    s.onclick=()=>{
      rating=i;
      stars.querySelectorAll(".star").forEach((x,j)=>{
        x.classList.toggle("selected",j<i);
      });
    };
    stars.appendChild(s);
  }

  const txt=document.createElement("textarea");
  txt.placeholder="Comentario (opcional)";
  txt.style.width="100%";

  const btn=document.createElement("button");
  btn.textContent="Enviar feedback";
  btn.onclick=()=>{
    fetch("/feedback",{
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body:JSON.stringify({question,answer,rating,comment:txt.value})
    }).then(()=>btn.textContent="Gracias 🙌");
  };

  box.append("Valoración: ",stars,document.createElement("br"),txt,btn);
  return box;
}

/* ================= CHAT BACKEND ================= */
function send(){
  const text=input.value.trim();
  if(!text) return;

  addUser(text);
  input.value="";
  typing.style.display="block";

  fetch("/chat",{
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body:JSON.stringify({question:text})
  })
  .then(r=>r.json())
  .then(d=>{
    typing.style.display="none";
    addBot(d.answer||"Sin respuesta",text);
  })
  .catch(()=>{
    typing.style.display="none";
    addBot("❌ Error de servidor",text);
  });
}

input.addEventListener("keydown",e=>{
  if(e.key==="Enter") send();
});
</script>

</body>
</html>
