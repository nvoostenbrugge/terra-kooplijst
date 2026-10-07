/* Terra Kooplijst: alle paden zijn relatief, zodat de pagina onder /kooplijst/ in TerraFlow werkt. */
(function () {
  "use strict";

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
  const slug = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "x";
  const DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"];
  function datum(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    return m ? m[3] + "-" + m[2] + "-" + m[1] : "";
  }
  function dagenGeleden(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return null;
    const toen = new Date(+m[1], +m[2] - 1, +m[3]);
    const nu = new Date(); nu.setHours(0, 0, 0, 0);
    return Math.round((nu - toen) / 86400000);
  }
  function nettelink(link) {
    let s = String(link || "").trim();
    if (!s) return "";
    if (!/^https?:\/\//i.test(s)) {
      if (/^[a-z0-9-]+(\.[a-z0-9-]+)+\//i.test(s)) s = "https://" + s; else return "";
    }
    try { return new URL(s).href; } catch (e) { return ""; }
  }
  function artikelnr(link) {
    const u = nettelink(link);
    if (!u) return "";
    const url = new URL(u), h = url.hostname, pad = url.pathname;
    let m;
    const dec = (x) => { try { return decodeURIComponent(x); } catch (e) { return x; } };
    if (/amazon\./.test(h)) { m = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})(?:[/?]|$)/.exec(pad); return m ? m[1] : ""; }
    if (/mouser\./.test(h)) { m = /\/ProductDetail\/[^/]+\/([^/?]+)/i.exec(pad); return m ? dec(m[1]) : ""; }
    if (/digikey\./.test(h)) { m = /\/products\/detail\/[^/]+\/([^/]+)/i.exec(pad); return m ? dec(m[1]) : ""; }
    if (/farnell\./.test(h)) { m = /\/dp\/([A-Z0-9]+)/i.exec(pad); return m ? m[1] : ""; }
    if (/rs-online\./.test(h)) { m = /\/web\/p\/[^/]+\/(\d+)/.exec(pad); return m ? m[1] : ""; }
    if (/tme\.eu/.test(h)) { m = /\/details\/([^/]+)/.exec(pad); return m ? dec(m[1]) : ""; }
    return "";
  }
  const BULK = /^(mouser\.com|digikey\.nl|digikey\.com|farnell\.com|rs-online\.com|tme\.eu)$/;
  let toastTimer;
  function toast(tekst) {
    const t = $("toast");
    t.textContent = tekst; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2800);
  }
  async function kopieer(tekst, klaar) {
    try { await navigator.clipboard.writeText(tekst); toast(klaar); }
    catch (e) { $("kopie-tekst").value = tekst; $("dlg-kopie").showModal(); $("kopie-tekst").select(); }
  }
  function lees(sleutel) { try { return localStorage.getItem(sleutel) || ""; } catch (e) { return ""; } }
  function bewaar(sleutel, v) { try { localStorage.setItem(sleutel, v); } catch (e) {} }
  function cookie(naam) {
    const m = document.cookie.match("(?:^|; )" + naam + "=([^;]*)");
    return m ? decodeURIComponent(m[1]) : "";
  }

  // ---------- server ----------
  class ApiFout extends Error {}
  async function api(pad, body, isFormulier) {
    const opties = { credentials: "same-origin", cache: "no-store", headers: {} };
    if (body !== undefined) {
      opties.method = "POST";
      opties.headers["X-CSRFToken"] = cookie("csrftoken");
      if (isFormulier) opties.body = body;
      else { opties.headers["Content-Type"] = "application/json"; opties.body = JSON.stringify(body); }
    }
    let r;
    try { r = await fetch(pad, opties); }
    catch (e) { throw new ApiFout("Geen verbinding met TerraFlow. Probeer het opnieuw."); }
    if (r.status === 401 || (r.redirected && /login/.test(r.url))) { location.reload(); throw new ApiFout("Je bent uitgelogd."); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* geen JSON */ }
    if (!r.ok) {
      if (data && data.staat) neemStaat(data.staat);
      throw new ApiFout((data && data.fout) || (r.status === 502 ? "De kooplijst-dienst reageert niet. Probeer het over een minuut opnieuw." : "Er ging iets mis (" + r.status + ")."));
    }
    if (data && data.staat) neemStaat(data.staat);
    return data || {};
  }

  // ---------- state ----------
  const S = {
    ik: null, regels: [], bestellingen: {}, wagens: {}, gebruikers: [], losseNamen: [], momenten: {},
    tab: location.hash.slice(1), tabGekozen: false, geladen: false,
    wie: "", uit: new Set(), open: new Set(), concept: {}, bezig: new Set(), fouten: {},
    zoek: "", statusFilter: "", bewerkId: null,
  };
  function neemStaat(st) {
    S.ik = st.ik; S.regels = st.regels || []; S.momenten = st.momenten || {};
    S.bestellingen = {}; (st.bestellingen || []).forEach((b) => { S.bestellingen[b.id] = b; });
    S.wagens = st.wagens || {}; S.gebruikers = st.gebruikers || []; S.losseNamen = st.losseNamen || [];
    S.geladen = true;
    render();
  }
  const staf = () => !!(S.ik && S.ik.zietAlles);
  const zichtbaar = (r) => !S.wie || String(r.aanvragerId || "n:" + r.aanvrager) === S.wie;
  const perStatus = (st) => S.regels.filter((r) => r.status === st && zichtbaar(r));
  const som = (lijst) => lijst.reduce((t, r) => t + (typeof r.prijs === "number" ? r.prijs : 0), 0);
  const stuks = (n) => n + (n === 1 ? " artikel" : " artikelen");
  function tabs() {
    const t = [];
    if (!staf()) t.push(["open", "Aangevraagd", S.regels.filter((r) => r.status === "aangevraagd" || r.status === "goedgekeurd").length]);
    if (S.ik.goedkeuren) t.push(["goedkeuren", "Goedkeuren", perStatus("aangevraagd").length]);
    if (S.ik.bestellen) t.push(["bestellen", "Bestellen", perStatus("goedgekeurd").length]);
    t.push(["onderweg", "Onderweg", perStatus("besteld").length]);
    t.push(["alles", "Alles", null]);
    return t;
  }

  // ---------- render ----------
  const STATUSNAAM = { aangevraagd: "Wacht op akkoord", goedgekeurd: "Akkoord", besteld: "Besteld", ontvangen: "Ontvangen", afgewezen: "Afgewezen" };
  function magWijzigen(r) { return staf() || (r.eigen && r.status === "aangevraagd"); }
  function pillen(r) {
    return (r.spoed ? ' <span class="pil spoed">Spoed</span>' : "") +
      (r.wachtTeLang ? ' <span class="pil laat">Wacht al ' + (dagenGeleden(r.aangevraagdOp) || 2) + " dagen</span>" : "") +
      (r.rondeGemist ? ' <span class="pil laat">Ronde gemist</span>' : "");
  }
  function regelMidden(r, opties) {
    const url = nettelink(r.link);
    const titel = esc(r.omschrijving || "(geen omschrijving)");
    const bij = [];
    if (opties.winkel) bij.push(esc(r.winkel || "geen link"));
    if (r.project) bij.push(esc(r.project));
    if (r.aanvrager && staf()) bij.push(esc(r.aanvrager));
    if (r.perVerpakking > 1) bij.push(esc(r.perVerpakking) + " per verpakking");
    if (opties.nummer && artikelnr(r.link)) bij.push('<span class="chip">' + esc(artikelnr(r.link)) + "</span>");
    if (opties.status) bij.push(esc(STATUSNAAM[r.status] || r.status));
    if (magWijzigen(r)) bij.push('<button class="tekstknop" type="button" data-act="wijzig" data-id="' + r.id + '">wijzig</button>');
    const extra = [];
    if (r.opmerking && !/^spoed$/i.test(r.opmerking)) extra.push(esc(r.opmerking));
    if (!url) extra.push("Link ontbreekt");
    if (opties.wagen && r.wagenOk !== null && r.wagenOk !== undefined) {
      extra.push(r.wagenOk
        ? '<span class="wagen-ok">In winkelwagen</span>' + (r.wagenNotitie ? " · " + esc(r.wagenNotitie) : "")
        : '<span class="wagen-nee">Niet in winkelwagen' + (r.wagenNotitie ? ": " + esc(r.wagenNotitie) : "") + "</span>");
    }
    return '<div class="midden"><div class="titel">' +
      (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + titel + "</a>" : titel) + pillen(r) + "</div>" +
      '<div class="bij">' + bij.join(" · ") + "</div>" +
      (extra.length ? '<div class="bij">' + extra.join(" · ") + "</div>" : "") + "</div>";
  }
  const prijsTekst = (r) => (typeof r.prijs === "number" ? '<span class="prijs">' + euro.format(r.prijs) + "</span>" : "");
  const uitgezet = (id) => (S.bezig.has(id) ? " disabled" : "");
  const namenVan = (rs) => esc(rs.map((r) => r.omschrijving || "(geen omschrijving)").join(", "));
  function groepKop(sleutel, titelHtml, metaHtml, subHtml, naastHtml) {
    const open = S.open.has(sleutel);
    return '<div class="groep' + (open ? " open" : "") + '"><div class="groep-kop">' +
      '<button class="g-knop" type="button" data-act="open" data-key="' + esc(sleutel) + '" aria-expanded="' + open + '">' +
      '<span class="pijl" aria-hidden="true">&#9656;</span><span class="g-titel">' + titelHtml + '</span><span class="g-meta">' + metaHtml + "</span>" +
      '<span class="g-sub">' + subHtml + "</span></button>" + (naastHtml || "") + "</div>";
  }
  function groepen(lijst, sleutelVan) {
    const g = new Map();
    lijst.forEach((r) => { const k = sleutelVan(r); if (!g.has(k)) g.set(k, []); g.get(k).push(r); });
    return g;
  }

  function viewOpen() {
    const lijst = S.regels.filter((r) => r.status === "aangevraagd" || r.status === "goedgekeurd");
    if (!lijst.length) return '<div class="leeg">Je hebt niets openstaan. Vraag iets aan met + Bestelling.</div>';
    return '<div class="lijst">' + lijst.map((r) =>
      '<div class="regel"><div class="aantal">' + esc(r.aantal) + "×</div>" + regelMidden(r, { winkel: true }) +
      '<div class="rechts">' + prijsTekst(r) + '<span class="pil s-' + esc(r.status) + '">' + esc(STATUSNAAM[r.status]) + "</span></div></div>"
    ).join("") + "</div>";
  }

  function viewGoedkeuren() {
    const lijst = perStatus("aangevraagd").sort((a, b) => (b.spoed - a.spoed) || (b.wachtTeLang - a.wachtTeLang));
    if (!lijst.length) return '<div class="leeg">Niets om goed te keuren.</div>';
    return '<div class="balk"><span>' + stuks(lijst.length) + ", samen " + euro.format(som(lijst)) + "</span>" +
      '<button class="btn klein" type="button" data-act="alles-akkoord"' + uitgezet("alles") + ">Alles akkoord</button></div>" +
      '<div class="lijst">' + lijst.map((r) =>
        '<div class="regel"><div class="aantal">' + esc(r.aantal) + "×</div>" + regelMidden(r, { winkel: true }) +
        '<div class="rechts">' + prijsTekst(r) +
        '<button class="btn klein stil" type="button" data-act="afwijzen" data-id="' + r.id + '"' + uitgezet("r" + r.id) + ">Afwijzen</button>" +
        '<button class="btn klein hoofd" type="button" data-act="akkoord" data-id="' + r.id + '"' + uitgezet("r" + r.id) + ">Akkoord</button></div></div>"
      ).join("") + "</div>";
  }

  function amazonLink(winkel, lijst) {
    const delen = [];
    lijst.forEach((r) => {
      const a = artikelnr(r.link);
      if (a) { const i = delen.length + 1; delen.push("ASIN." + i + "=" + a + "&Quantity." + i + "=" + Math.max(1, parseInt(r.aantal, 10) || 1)); }
    });
    return delen.length ? "https://www." + winkel + "/gp/aws/cart/add.html?" + delen.join("&") : "";
  }
  function wagenVan(winkel, rs) {
    const bekend = rs.filter((r) => r.wagenOk !== null && r.wagenOk !== undefined);
    if (!bekend.length) return null;
    const ok = rs.filter((r) => r.wagenOk === true).length;
    return { w: S.wagens[winkel] || {}, soort: ok === rs.length ? "klaar" : ok > 0 ? "deels" : "mislukt" };
  }
  const WAGENPIL = {
    klaar: '<span class="pil s-ontvangen">Winkelwagen klaar</span>',
    deels: '<span class="pil s-aangevraagd">Deels gevuld</span>',
    mislukt: '<span class="pil s-afgewezen">Niet gevuld</span>',
  };

  function viewBestellen() {
    const lijst = perStatus("goedgekeurd");
    if (!lijst.length) return '<div class="leeg">Niets te bestellen.</div>';
    const g = Array.from(groepen(lijst, (r) => r.winkel || "").entries())
      .sort((a, b) => (b[1].some((r) => r.spoed) - a[1].some((r) => r.spoed)) || (b[1].some((r) => r.rondeGemist) - a[1].some((r) => r.rondeGemist)) || (b[1].length - a[1].length));
    let html = '<div class="balk"><span>' + stuks(lijst.length) + " bij " + g.length + " winkels, samen " + euro.format(som(lijst)) + '</span></div><div class="lijst">';
    g.forEach(([winkel, rs]) => {
      const sk = slug(winkel || "geen-link"), sleutel = "b-" + sk;
      const wagen = wagenVan(winkel, rs);
      const wagenUrl = wagen && wagen.soort !== "mislukt" ? nettelink(wagen.w.url) : "";
      const eersteLink = nettelink((rs.find((r) => nettelink(r.link)) || {}).link);
      html += groepKop(sleutel,
        esc(winkel || "Geen link") + (rs.some((r) => r.spoed) ? ' <span class="pil spoed">Spoed</span>' : "") +
          (rs.some((r) => r.rondeGemist) ? ' <span class="pil laat">Ronde gemist</span>' : "") + (wagen ? " " + WAGENPIL[wagen.soort] : ""),
        stuks(rs.length) + " · " + euro.format(som(rs)), namenVan(rs),
        wagenUrl ? '<a class="btn klein hoofd" href="' + esc(wagenUrl) + '" target="_blank" rel="noopener">Open winkelwagen</a>'
          : eersteLink ? '<a class="btn klein" href="' + esc(new URL(eersteLink).origin) + '" target="_blank" rel="noopener">Open winkel</a>' : "");
      if (S.open.has(sleutel)) {
        const mee = rs.filter((r) => !S.uit.has(r.id));
        const amazon = /^amazon\./.test(winkel) ? amazonLink(winkel, mee) : "";
        const bulk = BULK.test(winkel) && mee.some((r) => artikelnr(r.link));
        html += '<div class="groep-lijf">';
        if (wagen && wagen.w.notitie) html += '<div class="wagen-noot">' + esc(wagen.w.notitie) + "</div>";
        html += rs.map((r) =>
          '<div class="regel' + (S.uit.has(r.id) ? " uit" : "") + '">' +
          '<label class="vink"><input type="checkbox" data-act="mee" data-id="' + r.id + '"' + (S.uit.has(r.id) ? "" : " checked") +
          ' aria-label="Meebestellen"><span class="aantal">' + esc(r.aantal) + "×</span></label>" +
          regelMidden(r, { nummer: bulk, wagen: true }) + '<div class="rechts">' + prijsTekst(r) + "</div></div>"
        ).join("");
        html += '<div class="afronden">';
        if (!wagenUrl && amazon) html += '<a class="btn klein" href="' + esc(amazon) + '" target="_blank" rel="noopener">Vul winkelwagen</a>';
        else if (!wagenUrl && bulk) html += '<button class="btn klein" type="button" data-act="kopieer-lijst" data-winkel="' + esc(winkel) + '">Kopieer artikellijst</button>';
        html += '<input type="text" id="on-' + sk + '" data-concept="on-' + sk + '" placeholder="Ordernummer" value="' + esc(S.concept["on-" + sk] || "") + '" autocomplete="off">' +
          '<button class="btn klein hoofd" type="button" data-act="besteld" data-winkel="' + esc(winkel) + '"' + (mee.length ? uitgezet("w-" + sk) : " disabled") + ">" +
          (mee.length === rs.length ? "Besteld" : mee.length + " van " + rs.length + " besteld") + "</button></div>";
        if (S.fouten[sleutel]) html += '<div class="fout">' + esc(S.fouten[sleutel]) + "</div>";
        html += "</div>";
      }
      html += "</div>";
    });
    return html + "</div>";
  }

  function viewOnderweg() {
    const lijst = perStatus("besteld");
    if (!lijst.length) return '<div class="leeg">Niets onderweg.</div>';
    const g = Array.from(groepen(lijst, (r) => r.bestellingId || 0).entries())
      .sort((a, b) => String(b[1][0].besteldOp).localeCompare(String(a[1][0].besteldOp)) || (b[0] - a[0]));
    let html = '<div class="balk"><span>' + stuks(lijst.length) + " in " + g.length + (g.length === 1 ? " bestelling" : " bestellingen") + '</span></div><div class="lijst">';
    g.forEach(([bid, rs]) => {
      const b = S.bestellingen[bid] || {}, sleutel = "o-" + bid;
      const dagen = dagenGeleden(rs[0].besteldOp);
      const track = nettelink(b.tracking);
      html += groepKop(sleutel,
        esc(rs[0].winkel || "Geen link") + (track ? ' <span class="pil s-besteld">' + esc(b.vervoerder || "Onderweg") + "</span>" : "") +
          (dagen !== null && dagen > 14 ? ' <span class="pil laat">' + dagen + " dagen</span>" : ""),
        esc(datum(rs[0].besteldOp).slice(0, 5)) + (b.ordernr && S.ik.bestellen ? " · " + esc(b.ordernr) : ""),
        namenVan(rs),
        track ? '<a class="btn klein" href="' + esc(track) + '" target="_blank" rel="noopener">Volg</a>' : "");
      if (S.open.has(sleutel)) {
        html += '<div class="groep-lijf">' + rs.map((r) =>
          '<div class="regel"><div class="aantal">' + esc(r.aantal) + "×</div>" + regelMidden(r, {}) +
          '<div class="rechts"><button class="btn klein" type="button" data-act="ontvangen" data-id="' + r.id + '"' + uitgezet("r" + r.id) + ">Ontvangen</button></div></div>"
        ).join("");
        let voet = "";
        if (S.ik.bestellen && bid) {
          voet += '<input type="text" id="tr-' + bid + '" data-concept="tr-' + bid + '" placeholder="' + (track ? "Andere volglink plakken" : "Volglink van de vervoerder plakken") + '" value="' + esc(S.concept["tr-" + bid] || "") + '" autocomplete="off">' +
            '<button class="btn klein" type="button" data-act="volglink" data-order="' + bid + '"' + uitgezet(sleutel) + ">Opslaan</button>";
        }
        if (rs.length > 1) voet += '<button class="btn klein hoofd duw" type="button" data-act="alles-ontvangen" data-order="' + bid + '"' + uitgezet(sleutel) + ">Alles ontvangen</button>";
        if (voet) html += '<div class="afronden">' + voet + "</div>";
        if (S.fouten[sleutel]) html += '<div class="fout">' + esc(S.fouten[sleutel]) + "</div>";
        html += "</div>";
      }
      html += "</div>";
    });
    return html + "</div>";
  }

  function viewAlles() {
    const q = S.zoek.trim().toLowerCase();
    let lijst = S.regels.filter(zichtbaar);
    if (S.statusFilter) lijst = lijst.filter((r) => r.status === S.statusFilter);
    if (q) lijst = lijst.filter((r) => [r.omschrijving, r.winkel, r.project, r.aanvrager, r.ordernr, r.factuurnr, r.opmerking].join(" ").toLowerCase().includes(q));
    lijst.sort((a, b) => String(b.besteldOp || b.aangevraagdOp).localeCompare(String(a.besteldOp || a.aangevraagdOp)) || (b.id - a.id));
    const totaal = lijst.length, toon = lijst.slice(0, 200), metStaf = staf();
    let html = '<div class="filters"><input type="search" id="zoek" placeholder="Zoek op artikel, winkel, project of ordernummer" value="' + esc(S.zoek) + '">' +
      '<select id="statusfilter" aria-label="Status"><option value="">Alle statussen</option>' +
      Object.keys(STATUSNAAM).map((k) => '<option value="' + k + '"' + (S.statusFilter === k ? " selected" : "") + ">" + STATUSNAAM[k] + "</option>").join("") + "</select></div>";
    if (!totaal) return html + '<div class="leeg">Geen regels gevonden.</div>';
    html += '<div class="balk"><span>' + totaal + (totaal === 1 ? " regel" : " regels") + (totaal > toon.length ? ", de eerste " + toon.length + " getoond" : "") + ", samen " + euro.format(som(lijst)) + "</span></div>";
    html += '<div class="tabel-wrap"><table><thead><tr><th>Status</th><th>Artikel</th>' + (metStaf ? "<th>Door</th>" : "") +
      '<th class="num">Prijs</th><th>Aangevraagd</th><th>Besteld</th>' + (metStaf ? "<th>Order</th><th>Factuur</th>" : "") + "</tr></thead><tbody>" +
      toon.map((r) => {
        const url = nettelink(r.link), titel = esc(r.aantal + "× " + (r.omschrijving || "(geen omschrijving)"));
        return '<tr><td><span class="pil s-' + esc(r.status) + '">' + esc(STATUSNAAM[r.status] || r.status) + "</span></td>" +
          '<td class="breed">' + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + titel + "</a>" : titel) +
          '<div class="bij">' + [esc(r.winkel || "geen link"), esc(r.project || "")].filter(Boolean).join(" · ") +
          (magWijzigen(r) ? ' · <button class="tekstknop" type="button" data-act="wijzig" data-id="' + r.id + '">wijzig</button>' : "") + "</div></td>" +
          (metStaf ? "<td>" + esc(r.aanvrager || "") + "</td>" : "") +
          '<td class="num">' + (typeof r.prijs === "number" ? euro.format(r.prijs) : "") + "</td>" +
          '<td class="mono">' + esc(datum(r.aangevraagdOp)) + '</td><td class="mono">' + esc(datum(r.besteldOp)) + "</td>" +
          (metStaf ? '<td class="mono">' + esc(r.ordernr || "") + '</td><td class="mono">' + esc(r.factuurnr || "") + "</td>" : "") + "</tr>";
      }).join("") + "</tbody></table></div>";
    return html;
  }

  function render() {
    if (!S.geladen) return;
    const lijst = tabs();
    if (!lijst.some((t) => t[0] === S.tab)) {
      const metWerk = lijst.find((t) => t[2] > 0);
      S.tab = S.tabGekozen ? lijst[0][0] : (metWerk ? metWerk[0] : lijst[0][0]);
    }
    $("tabs").innerHTML = lijst.map((t) =>
      '<button class="tab" role="tab" type="button" data-tab="' + t[0] + '" aria-selected="' + (t[0] === S.tab) + '">' + t[1] +
      (t[2] === null ? "" : ' <span class="tel">' + t[2] + "</span>") + "</button>").join("");
    $("beheer").hidden = !S.ik.admin;
    $("momenten").hidden = !S.ik.bestellen;

    // filter op aanvrager: alleen voor wie de hele lijst ziet
    const sel = $("wie");
    sel.hidden = !staf();
    if (staf()) {
      const namen = new Map();
      S.regels.forEach((r) => { if (r.aanvrager) namen.set(String(r.aanvragerId || "n:" + r.aanvrager), r.aanvrager); });
      const opties = '<option value="">Iedereen</option>' + Array.from(namen.entries()).sort((a, b) => a[1].localeCompare(b[1]))
        .map(([k, n]) => '<option value="' + esc(k) + '">' + esc(n) + "</option>").join("");
      if (sel.dataset.html !== opties) { sel.innerHTML = opties; sel.dataset.html = opties; }
      if (S.wie && !namen.has(S.wie)) S.wie = "";
      sel.value = S.wie;
    } else S.wie = "";
    const projecten = Array.from(new Set(S.regels.map((r) => String(r.project || "").trim()).filter(Boolean))).sort();
    $("projecten").innerHTML = projecten.map((p) => '<option value="' + esc(p) + '">').join("");

    const view = $("view");
    const actief = document.activeElement, focusId = actief && view.contains(actief) ? actief.id : "";
    const van = focusId && actief.selectionStart != null ? actief.selectionStart : null;
    view.innerHTML = S.tab === "open" ? viewOpen() : S.tab === "goedkeuren" ? viewGoedkeuren() : S.tab === "bestellen" ? viewBestellen()
      : S.tab === "onderweg" ? viewOnderweg() : viewAlles();
    if (focusId) {
      const terug = $(focusId);
      if (terug) { terug.focus(); if (van != null) { try { terug.setSelectionRange(van, van); } catch (e) {} } }
    }
  }

  // ---------- acties ----------
  async function metBezig(sleutel, werk, foutSleutel) {
    if (S.bezig.has(sleutel)) return;
    S.bezig.add(sleutel); render();
    try { await werk(); if (foutSleutel) delete S.fouten[foutSleutel]; }
    catch (e) {
      if (foutSleutel) S.fouten[foutSleutel] = e.message; else toast(e.message);
      api("api/staat/").then(neemStaat).catch(() => {});   // de lijst kan intussen door een ander gewijzigd zijn
    }
    S.bezig.delete(sleutel); render();
  }

  // ---------- formulier aanvraag ----------
  function toonFout(id, tekst) { const el = $(id); el.textContent = tekst || ""; el.hidden = !tekst; }
  function openFormulier(r) {
    S.bewerkId = r ? r.id : null;
    $("dlg-titel").textContent = r ? "Regel wijzigen" : "Nieuwe bestelling";
    $("f-opslaan").textContent = r ? "Opslaan" : "Aanvragen";
    $("f-link").value = r ? r.link || "" : "";
    $("f-omschrijving").value = r ? r.omschrijving || "" : "";
    $("f-aantal").value = r ? r.aantal || 1 : 1;
    $("f-per").value = r ? r.perVerpakking || 1 : 1;
    $("f-prijs").value = r && typeof r.prijs === "number" ? r.prijs.toFixed(2).replace(".", ",") : "";
    $("f-project").value = r ? r.project || "" : lees("kooplijst-project");
    $("f-opmerking").value = r ? r.opmerking || "" : "";
    $("f-spoed").checked = !!(r && r.spoed);
    const metStaf = !!r && staf();
    $("f-staf-rij").hidden = !metStaf;
    if (metStaf) {
      $("f-aanvrager").innerHTML = '<option value="">' + esc(r.aanvragerId ? "(niemand)" : (r.aanvrager ? r.aanvrager + " (niet gekoppeld)" : "(niemand)")) + "</option>" +
        S.gebruikers.map((g) => '<option value="' + g.id + '">' + esc(g.naam) + "</option>").join("");
      $("f-aanvrager").value = r.aanvragerId || "";
      const keuzes = r.status === "besteld" ? ["besteld", "ontvangen", "goedgekeurd"] : ["aangevraagd", "goedgekeurd", "afgewezen", "ontvangen"].filter((s) => s !== "ontvangen" || r.status === "ontvangen");
      if (!keuzes.includes(r.status)) keuzes.unshift(r.status);
      $("f-status").innerHTML = keuzes.map((s) => '<option value="' + s + '">' + STATUSNAAM[s] + "</option>").join("");
      $("f-status").value = r.status;
      $("f-factuur").value = r.factuurnr || "";
    }
    toonFout("f-fout", "");
    $("dlg-regel").showModal();
  }
  $("form-regel").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = {
      link: $("f-link").value.trim(), omschrijving: $("f-omschrijving").value.trim(),
      aantal: parseInt($("f-aantal").value, 10) || 1, perVerpakking: parseInt($("f-per").value, 10) || 1,
      prijs: $("f-prijs").value.trim(), project: $("f-project").value.trim(),
      opmerking: $("f-opmerking").value.trim(), spoed: $("f-spoed").checked,
    };
    if (S.bewerkId && !$("f-staf-rij").hidden) {
      body.status = $("f-status").value; body.factuurnr = $("f-factuur").value.trim();
      body.aanvragerId = $("f-aanvrager").value ? parseInt($("f-aanvrager").value, 10) : null;
    }
    $("f-opslaan").disabled = true;
    try {
      await api(S.bewerkId ? "api/regels/" + S.bewerkId + "/" : "api/regels/", body);
      if (!S.bewerkId) { bewaar("kooplijst-project", body.project); toast(body.spoed ? "Aangevraagd als spoed" : "Aangevraagd, wacht op akkoord"); }
      else toast("Opgeslagen");
      $("dlg-regel").close();
    } catch (e) { toonFout("f-fout", e.message); }
    $("f-opslaan").disabled = false;
  });

  // ---------- bestelmomenten ----------
  function uren(sel, gekozen) {
    let html = "";
    for (let u = 6; u <= 20; u++) html += '<option value="' + u + '"' + (u === gekozen ? " selected" : "") + ">" + String(u).padStart(2, "0") + ":00</option>";
    sel.innerHTML = html;
  }
  $("momenten").addEventListener("click", () => {
    const m = S.momenten || {};
    $("m-dagen").innerHTML = DAGEN.map((d, i) => '<label><input type="checkbox" value="' + i + '"' + ((m.dagen || []).includes(i) ? " checked" : "") + "> " + d + "</label>").join("");
    uren($("m-vul"), m.vul_uur); uren($("m-ronde"), m.ronde_uur);
    toonFout("m-fout", "");
    $("dlg-momenten").showModal();
  });
  $("form-momenten").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const dagen = Array.from($("m-dagen").querySelectorAll("input:checked")).map((i) => parseInt(i.value, 10));
    try {
      await api("api/instellingen/", { dagen: dagen, ronde_uur: parseInt($("m-ronde").value, 10), vul_uur: parseInt($("m-vul").value, 10) });
      $("dlg-momenten").close(); toast("Bestelmomenten opgeslagen");
    } catch (e) { toonFout("m-fout", e.message); }
  });

  // ---------- beheer ----------
  function renderBeheer() {
    $("b-team").innerHTML = S.gebruikers.map((g) =>
      '<div class="beheer-rij"><div><div>' + esc(g.naam) + (g.admin ? " (super-admin)" : "") + '</div><div class="mail">' + esc(g.email) + "</div></div>" +
      '<label><input type="checkbox" data-rol="goedkeuren" data-id="' + g.id + '"' + (g.goedkeuren || g.admin ? " checked" : "") + (g.admin ? " disabled" : "") + "> Goedkeuren</label>" +
      '<label><input type="checkbox" data-rol="bestellen" data-id="' + g.id + '"' + (g.bestellen || g.admin ? " checked" : "") + (g.admin ? " disabled" : "") + "> Bestellen</label></div>"
    ).join("");
    $("b-namen-blok").hidden = !S.losseNamen.length;
    $("b-namen").innerHTML = S.losseNamen.map((n) =>
      '<div class="beheer-rij"><div>' + esc(n) + '</div><select data-naam="' + esc(n) + '"><option value="">Koppel aan…</option>' +
      S.gebruikers.map((g) => '<option value="' + g.id + '">' + esc(g.naam) + "</option>").join("") + "</select><span></span></div>").join("");
  }
  $("beheer").addEventListener("click", () => { renderBeheer(); toonFout("b-fout", ""); $("b-uitkomst").textContent = ""; $("b-email").value = ""; $("dlg-beheer").showModal(); });
  $("dlg-beheer").addEventListener("change", async (ev) => {
    const el = ev.target;
    try {
      if (el.dataset.rol) {
        const g = S.gebruikers.find((x) => x.id === parseInt(el.dataset.id, 10));
        const nieuw = { id: g.id, goedkeuren: g.goedkeuren, bestellen: g.bestellen };
        nieuw[el.dataset.rol] = el.checked;
        await api("api/team/", nieuw); renderBeheer();
      } else if (el.dataset.naam && el.value) {
        const d = await api("api/koppel/", { naam: el.dataset.naam, id: parseInt(el.value, 10) });
        toast(d.aantal + (d.aantal === 1 ? " regel gekoppeld" : " regels gekoppeld")); renderBeheer();
      }
    } catch (e) { toonFout("b-fout", e.message); renderBeheer(); }
  });
  $("b-voegtoe").addEventListener("click", async () => {
    try { await api("api/team/", { email: $("b-email").value.trim(), goedkeuren: false, bestellen: false }); $("b-email").value = ""; toonFout("b-fout", ""); renderBeheer(); }
    catch (e) { toonFout("b-fout", e.message); }
  });
  async function inladen(proef) {
    const bestand = $("b-bestand").files[0];
    if (!bestand) { toonFout("b-fout", "Kies eerst het Excel-bestand."); return; }
    const fd = new FormData(); fd.append("bestand", bestand); if (proef) fd.append("proef", "1");
    $("b-uitkomst").textContent = "Bezig…"; toonFout("b-fout", "");
    try {
      const d = await api("api/import/", fd, true), t = d.geteld;
      $("b-uitkomst").textContent = (proef ? "Proefdraai, er is niets opgeslagen. " : "Ingeladen. ") + "Tabblad " + d.blad + ": " +
        t.aangevraagd + " wachten op akkoord, " + t.goedgekeurd + " akkoord, " + t.besteld + " besteld. " +
        t.dubbel + " stonden er al in, " + t.overgeslagen + " overgeslagen (oud, ontvangen of geannuleerd).";
      renderBeheer();
    } catch (e) { $("b-uitkomst").textContent = ""; toonFout("b-fout", e.message); }
  }
  $("b-proef").addEventListener("click", () => inladen(true));
  $("b-inladen").addEventListener("click", () => inladen(false));

  // ---------- events ----------
  document.addEventListener("click", (ev) => { const b = ev.target.closest("[data-sluit]"); if (b) $(b.dataset.sluit).close(); });
  $("nieuw").addEventListener("click", () => openFormulier(null));
  $("tabs").addEventListener("click", (ev) => {
    const t = ev.target.closest(".tab");
    if (!t) return;
    S.tab = t.dataset.tab; S.tabGekozen = true;
    try { history.replaceState(null, "", "#" + S.tab); } catch (e) {}
    render();
  });
  $("wie").addEventListener("change", (ev) => { S.wie = ev.target.value; render(); });
  $("view").addEventListener("input", (ev) => {
    const el = ev.target;
    if (el.id === "zoek") { S.zoek = el.value; render(); return; }
    if (el.dataset && el.dataset.concept) S.concept[el.dataset.concept] = el.value;
  });
  $("view").addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.id === "statusfilter") { S.statusFilter = el.value; render(); return; }
    if (el.dataset.act === "mee") { const id = parseInt(el.dataset.id, 10); if (el.checked) S.uit.delete(id); else S.uit.add(id); render(); }
  });
  $("view").addEventListener("click", (ev) => {
    const el = ev.target.closest("button[data-act]");
    if (!el) return;
    const act = el.dataset.act, id = parseInt(el.dataset.id, 10), winkel = el.dataset.winkel, order = parseInt(el.dataset.order, 10);
    if (act === "open") { const k = el.dataset.key; if (S.open.has(k)) S.open.delete(k); else S.open.add(k); render(); return; }
    const teBestellen = () => perStatus("goedgekeurd").filter((r) => (r.winkel || "") === winkel && !S.uit.has(r.id));

    if (act === "wijzig") { const r = S.regels.find((x) => x.id === id); if (r) openFormulier(r); }
    else if (act === "akkoord") metBezig("r" + id, () => api("api/regels/" + id + "/akkoord/", {}));
    else if (act === "afwijzen") metBezig("r" + id, async () => { await api("api/regels/" + id + "/afwijzen/", {}); toast("Afgewezen. Terugzetten kan onder Alles."); });
    else if (act === "alles-akkoord") metBezig("alles", () => api("api/akkoord/", { ids: perStatus("aangevraagd").map((r) => r.id) }));
    else if (act === "kopieer-lijst") kopieer(teBestellen().filter((r) => artikelnr(r.link)).map((r) => artikelnr(r.link) + "," + r.aantal).join("\n"), "Artikellijst gekopieerd");
    else if (act === "besteld") {
      const sk = slug(winkel || "geen-link");
      metBezig("w-" + sk, async () => {
        const d = await api("api/besteld/", { winkel: winkel, ordernr: String(S.concept["on-" + sk] || "").trim(), ids: teBestellen().map((r) => r.id) });
        delete S.concept["on-" + sk];
        toast(stuks(d.aantal) + " op besteld gezet");
      }, "b-" + sk);
    }
    else if (act === "ontvangen") metBezig("r" + id, () => api("api/ontvangen/", { ids: [id] }));
    else if (act === "alles-ontvangen") metBezig("o-" + order, () => api("api/ontvangen/", { ids: perStatus("besteld").filter((r) => r.bestellingId === order).map((r) => r.id) }));
    else if (act === "volglink") metBezig("o-" + order, async () => {
      const d = await api("api/bestellingen/" + order + "/volglink/", { url: String(S.concept["tr-" + order] || "").trim() });
      delete S.concept["tr-" + order];
      toast(d.vervoerder ? "Volglink van " + d.vervoerder + " opgeslagen" : "Volglink verwijderd");
    }, "o-" + order);
  });

  // ---------- start ----------
  async function ververs() {
    if (document.hidden || document.querySelector("dialog[open]") || S.bezig.size) return;
    try { neemStaat(await api("api/staat/")); $("melding").hidden = true; }
    catch (e) { $("melding").textContent = e.message; $("melding").hidden = false; }
  }
  api("api/staat/").then(neemStaat).catch((e) => { $("view").innerHTML = '<div class="leeg">' + esc(e.message) + "</div>"; });
  setInterval(ververs, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) ververs(); });
})();
