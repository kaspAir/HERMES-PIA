// Adaptives Interview – Gespräch und «Für den PIA erkannt».
//
// Grundsätze:
// - EIN Lesemodell, EINE Zeichenfunktion. Erstanzeige und jede Aktualisierung
//   gehen durch dieselbe Funktion; es gibt keine zweite Darstellung.
// - Revisionsschutz: eine Antwort mit älterer Revision als der angezeigten
//   wird verworfen – eine verspätete Antwort überschreibt keinen neueren Stand.
// - Während der Verarbeitung bleibt der letzte konsistente Stand sichtbar;
//   ein Statustext sagt, was gerade passiert.
// - Fokus und Bildlauf bleiben bei Aktualisierungen erhalten; Änderungen
//   werden über eine aria-live-Region angesagt.
// - Benutzer- und Modelltexte gehen ausschliesslich über textContent in die
//   Seite (kein innerHTML mit Inhalten).
(function () {
  'use strict';

  var wege = JSON.parse(document.getElementById('ai-wege').textContent);
  var ansicht = JSON.parse(document.getElementById('ai-daten').textContent);
  var angezeigt = ansicht.revision || 0;
  var beschaeftigt = false;
  var offeneAnfrage = null;          // Anfrage-ID bleibt bis zum Erfolg gleich (Idempotenz)
  var bericht = null;                // letzte Abschlussprüfung – gilt nur für ihre Revision

  var el = {
    verlauf: document.getElementById('ai-verlauf'),
    frage: document.getElementById('ai-frage'),
    form: document.getElementById('ai-eingabe'),
    text: document.getElementById('answer-text'),
    senden: document.getElementById('ai-senden'),
    status: document.getElementById('ai-status'),
    reife: document.getElementById('ai-reife'),
    kurz: document.getElementById('ai-kurzstatus'),
    aside: document.getElementById('ai-erkannt'),
    panel: document.getElementById('ai-panel-erkannt'),
    vorschau: document.getElementById('ai-panel-vorschau'),
    tabErkannt: document.getElementById('tab-erkannt'),
    tabVorschau: document.getElementById('tab-vorschau'),
    ansage: document.getElementById('ai-ansage')
  };

  var SCHRITT_TEXT = {
    formulierung: 'Ausgangslage wird formuliert …',
    rag: 'Vergleichsprojekte werden geprüft …',
    frage: 'Nächste Frage wird gewählt …'
  };

  // ---- Hilfen ----------------------------------------------------------- //

  function knoten(tag, klasse, text) {
    var n = document.createElement(tag);
    if (klasse) n.className = klasse;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function anfrageId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'a' + Date.now() + Math.random().toString(16).slice(2);
  }

  function setzeStatus(text, fehler) {
    el.status.textContent = text || '';
    el.status.classList.toggle('ai-status--fehler', !!fehler);
  }

  function sende(url, daten, methode) {
    return fetch(url, {
      method: methode || 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: methode === 'GET' ? undefined : JSON.stringify(daten || {}),
      credentials: 'same-origin'
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) { var e = new Error(d.fehler || ('Fehler ' + r.status)); e.daten = d; throw e; }
        return d;
      });
    });
  }

  // ---- Zeichnen ---------------------------------------------------------- //

  var ersteZeichnung = true;

  function zeichneVerlauf(nachrichten, frage) {
    // Beim ersten Zeichnen und wenn man ohnehin unten war: zum neuesten Beitrag.
    // Wer nach oben gescrollt hat, um etwas nachzulesen, wird nicht weggerissen.
    var unten = ersteZeichnung ||
      el.verlauf.scrollHeight - el.verlauf.scrollTop - el.verlauf.clientHeight < 40;
    ersteZeichnung = false;
    el.verlauf.textContent = '';
    // Die offene Frage steht in der Fragekarte – nicht zusätzlich im Verlauf.
    var offenId = frage && frage.nachricht_id;
    (nachrichten || []).forEach(function (m) {
      if (offenId && m.id === offenId) return;
      var offen = m.rolle === 'benutzer' && (m.status === 'fehler' || m.status === 'blockiert');
      var li = knoten('li', 'ai-nachricht ai-nachricht--' + m.rolle +
                            (offen ? ' ai-nachricht--fehler' : ''));
      li.appendChild(knoten('span', 'wer', m.rolle === 'benutzer' ? 'Du' : 'HERMES PIA'));
      li.appendChild(knoten('span', '', m.text));
      if (offen) {
        li.appendChild(knoten('div', 'zusatz', m.status === 'blockiert'
          ? 'Von der Pseudonymisierung angehalten – nichts wurde gesendet. Entscheide je Fundstelle, dann wird der Beitrag unverändert verarbeitet.'
          : 'Nicht ausgewertet – der Beitrag ist gespeichert.'));
        // Ein echtes Formular: die Entscheidungsseite der Pseudonymisierung
        // wiederholt genau diesen Aufruf, mit Anmeldung und Rechten.
        var f = knoten('form', 'ai-inline-form');
        f.method = 'post';
        f.action = wege.verarbeiten.replace('/0/', '/' + m.id + '/');
        var b = knoten('button', 'ai-linkknopf', m.status === 'blockiert'
          ? 'Fundstellen prüfen und verarbeiten' : 'Erneut verarbeiten');
        b.type = 'submit';
        f.appendChild(b);
        li.appendChild(f);
      }
      el.verlauf.appendChild(li);
    });
    if (unten) el.verlauf.scrollTop = el.verlauf.scrollHeight;
  }

  function zeichneFrage(frage) {
    el.frage.textContent = '';
    if (!frage || !frage.frage) return;
    el.frage.appendChild(knoten('p', 'frage-text', frage.frage));
    if (frage.begruendung) {
      var d = knoten('details');
      d.appendChild(knoten('summary', '', 'Warum diese Frage?'));
      d.appendChild(knoten('p', '', frage.begruendung));
      el.frage.appendChild(d);
    }
    var akt = knoten('div', 'frage-aktionen');
    [['frage_unklar', 'Frage ist unklar'], ['schon_beantwortet', 'Habe ich schon beantwortet']]
      .forEach(function (paar) {
        var b = knoten('button', 'ai-linkknopf', paar[1]);
        b.type = 'button';
        b.dataset.fokus = 'rm-' + paar[0];
        b.addEventListener('click', function () { rueckmeldung(paar[0]); });
        akt.appendChild(b);
      });
    el.frage.appendChild(akt);
  }

  function marke(text, klasse) { return knoten('span', 'ai-marke ' + (klasse || ''), text); }

  function eintrag(e, art) {
    var li = knoten('li', 'ai-eintrag' + (e.neu ? ' ai-eintrag--neu' : '') +
                          (e.geaendert ? ' ai-eintrag--geaendert' : '') +
                          (art ? ' ai-eintrag--' + art : ''));
    li.appendChild(knoten('p', 'inhalt', e.inhalt || e.beschreibung || e.thema));
    var meta = knoten('div', 'ai-meta');
    if (e.neu) meta.appendChild(marke('Neu', 'ai-marke--neu'));
    if (e.geaendert) meta.appendChild(marke('Geändert', 'ai-marke--geaendert'));
    if (e.status_text) meta.appendChild(marke(e.status_text, 'ai-marke--status'));
    (e.ziele || []).forEach(function (z) {
      meta.appendChild(marke(z.nicht_anwendbar ? ('Kap. ' + z.kapitel + ': nicht anwendbar')
                                               : ('→ Kap. ' + z.kapitel), 'ai-marke--kapitel'));
    });
    li.appendChild(meta);
    if (e.hinweise && e.hinweise.length) {
      var ul = knoten('ul', 'ai-hinweise');
      e.hinweise.forEach(function (h) { ul.appendChild(knoten('li', '', h)); });
      li.appendChild(ul);
    }
    if (e.schluessel && e.aktionen && e.aktionen.length) {
      var akt = knoten('div', 'ai-aktionen');
      e.aktionen.forEach(function (a) {
        var t = { bestaetigen: 'Bestätigen', berichtigen: 'Berichtigen', verwerfen: 'Verwerfen' }[a];
        var b = knoten('button', '', t);
        b.type = 'button';
        b.dataset.fokus = a + '-' + e.schluessel;
        b.setAttribute('aria-label', t + ': ' + (e.inhalt || '').slice(0, 80));
        b.addEventListener('click', function () {
          if (a === 'berichtigen') { zeigeBerichtigen(li, e); } else { aussageAktion(e.schluessel, a); }
        });
        akt.appendChild(b);
      });
      li.appendChild(akt);
    }
    if (e.original) {
      var d = knoten('details', 'ai-details');
      d.appendChild(knoten('summary', '', 'Dein Originalbeitrag'));
      d.appendChild(knoten('p', '', e.original));
      li.appendChild(d);
    }
    return li;
  }

  function zeigeBerichtigen(li, e) {
    if (li.querySelector('.ai-berichtigen')) return;
    var box = knoten('div', 'ai-berichtigen');
    var ta = knoten('textarea');
    ta.value = e.inhalt;
    ta.setAttribute('aria-label', 'Berichtigung von ' + e.schluessel);
    var ok = knoten('button', 'btn-primary', 'Berichtigung senden');
    ok.type = 'button';
    ok.addEventListener('click', function () {
      if (!ta.value.trim()) return;
      sendeBeitrag('Korrektur zu «' + e.inhalt + '»: ' + ta.value.trim(), e.schluessel);
    });
    box.appendChild(ta);
    box.appendChild(ok);
    li.appendChild(box);
    ta.focus();
  }

  function abschnitt(titel, hinweis) {
    var frag = document.createDocumentFragment();
    frag.appendChild(knoten('h2', '', titel));
    if (hinweis) frag.appendChild(knoten('p', 'ai-hinweistext', hinweis));
    return frag;
  }

  function zeichneErkannt(a) {
    var erk = a.erkannt || {};
    var fokus = document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.fokus : null;
    var lauf = el.panel.scrollTop;
    el.panel.textContent = '';

    // Abschlussreife
    var reife = (erk.reife || {});
    var box = knoten('div', 'ai-reifebox');
    var bereit = reife.zustand === 'bereit_zur_pruefung';
    box.appendChild(knoten('strong', '', bereit ? 'Bereit zur Benutzerprüfung'
                                                : 'Entwurf – noch offene Punkte'));
    if (!bereit && erk.blocker && erk.blocker.length) {
      var ul = knoten('ul');
      erk.blocker.slice(0, 6).forEach(function (b) {
        ul.appendChild(knoten('li', '', 'Kap. ' + b.kapitel + ': ' + b.beschreibung +
                                        ' (' + b.zustand_text + ', ' + b.gewicht_text + ')'));
      });
      if (erk.blocker.length > 6) ul.appendChild(knoten('li', '', '… und ' + (erk.blocker.length - 6) + ' weitere'));
      box.appendChild(ul);
    }
    zeichneAbschluss(box, a, bereit);
    el.panel.appendChild(box);

    // Offenes und Widersprüche zuerst – nicht zwischen Bestätigtem verstecken.
    var offen = (erk.konflikte || []).length + (erk.offen || []).length;
    if (offen) {
      el.panel.appendChild(abschnitt('Offen und zu bestätigen'));
      var liste = knoten('ul', 'ai-liste');
      (erk.konflikte || []).forEach(function (k) {
        liste.appendChild(eintrag({ beschreibung: k.beschreibung, status_text: k.status_text,
                                    neu: k.neu }, 'konflikt'));
      });
      var vorschlaege = [];
      (erk.offen || []).forEach(function (e) {
        liste.appendChild(eintrag(e, 'offen'));
        if (!e.bestaetigt && e.aktionen.indexOf('bestaetigen') >= 0 && e.herkunft !== 'benutzer') {
          vorschlaege.push(e.schluessel);
        }
      });
      el.panel.appendChild(liste);
      if (vorschlaege.length > 1) {
        var alle = knoten('button', 'ai-linkknopf', 'Alle ' + vorschlaege.length + ' Vorschläge übernehmen');
        alle.type = 'button';
        alle.dataset.fokus = 'alle-vorschlaege';
        alle.addEventListener('click', function () { sammel(vorschlaege); });
        el.panel.appendChild(alle);
      }
    }

    // Erkannte Angaben, thematisch gegliedert
    (erk.gruppen || []).forEach(function (g) {
      el.panel.appendChild(abschnitt(g.titel));
      var ul = knoten('ul', 'ai-liste');
      g.eintraege.forEach(function (e) { ul.appendChild(eintrag(e)); });
      el.panel.appendChild(ul);
    });
    if (!(erk.gruppen || []).length && !offen) {
      el.panel.appendChild(knoten('p', 'ai-leer', 'Noch nichts erkannt – erzähl vom Vorhaben, ' +
                                                 'die Angaben erscheinen hier laufend.'));
    }

    // RAG-Themen getrennt – nie unter «von Dir genannt»
    var rag = erk.rag || {};
    el.panel.appendChild(abschnitt('Mögliche Klärungspunkte aus Vergleichsprojekten',
      rag.verfuegbar === false ? (rag.grund || 'Vergleichsprojekte nicht verfügbar.')
                               : 'Anhaltspunkte aus früheren Vorhaben – kein Befund über Dein Projekt.'));
    if ((erk.themen || []).length) {
      var tl = knoten('ul', 'ai-liste');
      erk.themen.forEach(function (t) {
        var li = eintrag({ inhalt: t.thema, status_text: t.status_text, neu: t.neu,
                           ziele: t.ziele, hinweise: [t.frage_ansatz, 'Aus ' + t.n_projekte +
                           ' Vergleichsprojekt(en)'].filter(Boolean) }, 'rag');
        var akt = knoten('div', 'ai-aktionen');
        [['passt', 'Ist relevant', true], ['passtnicht', 'Passt nicht', false]].forEach(function (p) {
          var b = knoten('button', '', p[1]);
          b.type = 'button';
          b.dataset.fokus = p[0] + '-' + t.id;
          b.addEventListener('click', function () { themaBewerten(t.id, p[2]); });
          akt.appendChild(b);
        });
        var q = knoten('button', '', 'Quelle ansehen');
        q.type = 'button';
        q.dataset.fokus = 'quelle-' + t.id;
        q.addEventListener('click', function () { zeigeQuelle(li, t.id); });
        akt.appendChild(q);
        li.appendChild(akt);
        tl.appendChild(li);
      });
      el.panel.appendChild(tl);
    }

    // Kopf und Kurzstatus
    var z = erk.zaehler || {};
    el.reife.textContent = '';
    el.reife.appendChild(knoten('strong', '', bereit ? 'Bereit zur Prüfung' : 'Entwurf'));
    el.reife.appendChild(document.createTextNode(' · ' + (z.aussagen || 0) + ' Angaben · ' +
                                                  (z.offen || 0) + ' offen'));
    el.kurz.textContent = 'Für den PIA erkannt: ' + (z.aussagen || 0) + ' Angaben · ' +
      (z.neu || 0) + ' neu · ' + (z.geaendert || 0) + ' geändert · ' + (z.offen || 0) +
      ' offen  ' + (el.aside.classList.contains('offen') ? '▲' : '▼');

    el.panel.scrollTop = lauf;
    if (fokus) {
      var ziel = el.panel.querySelector('[data-fokus="' + fokus + '"]') ||
                 el.frage.querySelector('[data-fokus="' + fokus + '"]');
      if (ziel) ziel.focus();
    }
  }

  // Abschlussprüfung: zeigt Blocker, Annahmen, Korrekturen und offene
  // Vertiefungen. Fertigstellen gilt nur für die geprüfte Revision.
  function zeichneAbschluss(box, a, bereit) {
    if (bericht && bericht.revision !== a.revision) bericht = null;
    if (a.pia_status === 'fertiggestellt') {
      box.appendChild(knoten('p', 'ai-abschluss-ok',
        'Fertiggestellt von der Projektleitung (Stand ' + a.revision + '). ' +
        'Prüfung und Freigabe erfolgen durch die zuständigen Personen.'));
      return;
    }
    var pruefen = knoten('button', 'ai-linkknopf', 'Abschluss prüfen');
    pruefen.type = 'button';
    pruefen.dataset.fokus = 'abschluss-pruefen';
    pruefen.addEventListener('click', function () { abschluss('pruefen'); });
    box.appendChild(pruefen);
    if (!bericht) return;
    var b = bericht.daten;
    var d = knoten('div', 'ai-abschluss');
    if (b.annahmen.length) {
      d.appendChild(knoten('p', '', 'Als Annahme im Dokument (vermerkt «unbestätigt»):'));
      var ua = knoten('ul');
      b.annahmen.forEach(function (x) { ua.appendChild(knoten('li', '', x)); });
      d.appendChild(ua);
    }
    d.appendChild(knoten('p', '', b.korrekturen + ' Korrektur(en) im Verlauf.'));
    if (b.unbestaetigt.length) {
      d.appendChild(knoten('p', '', b.unbestaetigt.length +
        ' Angabe(n) nicht übernommen – sie stehen nicht im Dokument.'));
    }
    if (b.vertiefungen_offen.length) {
      d.appendChild(knoten('p', '', 'Offene Vertiefungen (blockieren nicht): ' +
                                    b.vertiefungen_offen.join('; ')));
    }
    d.appendChild(knoten('p', 'ai-hinweistext', b.hinweis));
    if (b.bereit && bereit) {
      var f = knoten('button', 'btn-primary', 'Fertigstellen');
      f.type = 'button';
      f.dataset.fokus = 'abschluss-fertig';
      f.addEventListener('click', function () { abschluss('fertigstellen'); });
      d.appendChild(f);
    }
    box.appendChild(d);
  }

  function abschluss(aktion) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    setzeStatus(aktion === 'pruefen' ? 'Abschluss wird geprüft …' : 'Wird fertiggestellt …');
    sende(wege.abschluss, { aktion: aktion, revision: angezeigt })
      .then(function (a) {
        beschaeftigt = false;
        if (a.abschluss) bericht = { revision: a.revision, daten: a.abschluss };
        uebernehme(a);
        zeichneErkannt(a);
        setzeStatus(aktion === 'fertigstellen' ? 'Fertiggestellt.' : '');
      })
      .catch(function (e) { beschaeftigt = false; setzeStatus('Nicht ausgeführt: ' + e.message, true); });
  }

  function ansagen(a) {
    var z = (a.erkannt || {}).zaehler || {};
    var teile = [];
    if (z.neu) teile.push(z.neu + (z.neu === 1 ? ' neue' : ' neue') + ' Erkenntnis' + (z.neu === 1 ? '' : 'se'));
    if (z.geaendert) teile.push(z.geaendert + ' geändert');
    el.ansage.textContent = teile.length ? ('Für den PIA erkannt: ' + teile.join(', ') + '.') : '';
  }

  function uebernehme(a) {
    if (!a || typeof a.revision !== 'number') return false;
    if (a.revision < angezeigt) return false;           // veraltet – verwerfen
    angezeigt = a.revision;
    ansicht = a;
    zeichneVerlauf(a.nachrichten, a.frage);
    zeichneFrage(a.frage);
    zeichneErkannt(a);
    ansagen(a);
    return true;
  }

  // ---- Aktionen ----------------------------------------------------------- //

  function weiterSchleife(rest) {
    if (!rest || !rest.length) {
      beschaeftigt = false;
      el.senden.disabled = false;
      setzeStatus('');
      return Promise.resolve();
    }
    setzeStatus(SCHRITT_TEXT[rest[0]] || 'Wird verarbeitet …');
    return sende(wege.weiter, {}).then(function (a) {
      uebernehme(a);
      if (a.hinweis) setzeStatus(a.hinweis);
      return weiterSchleife(a.ausstehend);
    }).catch(function (e) {
      beschaeftigt = false;
      el.senden.disabled = false;
      setzeStatus('Ein Verarbeitungsschritt ist fehlgeschlagen (' + e.message +
                  '). Der bisherige Stand bleibt erhalten.', true);
    });
  }

  function sendeBeitrag(text, korrekturVon) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    el.senden.disabled = true;
    if (!offeneAnfrage) offeneAnfrage = anfrageId();
    setzeStatus('Dein Beitrag ist gespeichert und wird ausgewertet …');
    sende(wege.beitrag, { text: text, anfrage_id: offeneAnfrage, korrektur_von: korrekturVon || null })
      .then(function (a) {
        offeneAnfrage = null;
        if (!korrekturVon) el.text.value = '';
        uebernehme(a);
        if (a.fehler) {
          beschaeftigt = false;
          el.senden.disabled = false;
          setzeStatus(a.fehler, true);
          return;
        }
        if (a.aenderung && a.aenderung.bezug_unklar) setzeStatus('Rückfrage: ' + a.aenderung.bezug_unklar);
        return weiterSchleife(a.ausstehend);
      })
      .catch(function (e) {
        // Anfrage-ID bleibt: ein erneutes Senden wird nicht doppelt verarbeitet.
        beschaeftigt = false;
        el.senden.disabled = false;
        setzeStatus('Verbindung unterbrochen (' + e.message + '). Dein Text ist noch im Feld – ' +
                    'erneut senden ist sicher.', true);
      });
    el.text.focus();
  }

  function aussageAktion(schluessel, aktion) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    setzeStatus(aktion === 'bestaetigen' ? 'Wird bestätigt …' : 'Wird verworfen …');
    sende(wege.aussage.replace('SCHLUESSEL', encodeURIComponent(schluessel)), { aktion: aktion })
      .then(function (a) { uebernehme(a); if (a.fehler) setzeStatus(a.fehler, true);
                           return weiterSchleife(a.ausstehend); })
      .catch(function (e) { beschaeftigt = false; setzeStatus('Nicht ausgeführt: ' + e.message, true); });
  }

  function sammel(schluessel) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    setzeStatus('Vorschläge werden übernommen …');
    sende(wege.bestaetigen, { schluessel: schluessel })
      .then(function (a) { uebernehme(a); return weiterSchleife(a.ausstehend); })
      .catch(function (e) { beschaeftigt = false; setzeStatus('Nicht ausgeführt: ' + e.message, true); });
  }

  function themaBewerten(id, passt) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    sende(wege.thema.replace(/\/0$/, '/' + id), { passt: passt })
      .then(function (a) { uebernehme(a); return weiterSchleife(a.ausstehend); })
      .catch(function (e) { beschaeftigt = false; setzeStatus('Nicht ausgeführt: ' + e.message, true); });
  }

  function rueckmeldung(art) {
    if (beschaeftigt) return;
    beschaeftigt = true;
    setzeStatus('Danke – die Frage wird neu gewählt …');
    sende(wege.rueckmeldung, { art: art })
      .then(function (a) { uebernehme(a); return weiterSchleife(a.ausstehend); })
      .catch(function (e) { beschaeftigt = false; setzeStatus('Nicht ausgeführt: ' + e.message, true); });
  }

  function zeigeQuelle(li, id) {
    if (li.querySelector('.ai-quelle')) return;
    sende(wege.quelle.replace(/\/0$/, '/' + id), null, 'GET').then(function (q) {
      var d = knoten('details', 'ai-details ai-quelle');
      d.open = true;
      d.appendChild(knoten('summary', '', 'Fundstellen (' + q.quellen.length + ') · Regel ' + q.regel +
                                          ' v' + q.regel_version));
      if (q.begruendung) d.appendChild(knoten('p', '', 'Übertragung: ' + q.begruendung));
      q.quellen.forEach(function (s) {
        d.appendChild(knoten('p', '', '«' + s.auszug + '» – ' + (s.abschnitt || 'ohne Abschnitt') +
          ', ' + (s.methodenversion || 'Version unbekannt') +
          (s.methodenversion_herkunft ? ' (' + s.methodenversion_herkunft + ')' : '')));
      });
      li.appendChild(d);
    }).catch(function (e) { setzeStatus('Quelle nicht verfügbar: ' + e.message, true); });
  }

  // ---- Vorschau (gleiche Projektion wie der Export) ------------------------ //

  function zeigeTab(vorschau) {
    el.tabErkannt.setAttribute('aria-selected', vorschau ? 'false' : 'true');
    el.tabVorschau.setAttribute('aria-selected', vorschau ? 'true' : 'false');
    el.panel.hidden = !!vorschau;
    el.vorschau.hidden = !vorschau;
    if (!vorschau) return;
    el.vorschau.textContent = 'Lädt …';
    sende(wege.vorschau, null, 'GET').then(function (v) {
      el.vorschau.textContent = '';
      el.vorschau.appendChild(knoten('p', 'ai-hinweistext',
        'Stand Revision ' + v.revision + ' – dieselben Daten wie der Word-Export.'));
      (v.abschnitte || []).forEach(function (s) {
        el.vorschau.appendChild(knoten('h2', '', s.number + ' ' + s.title));
        if (s.type === 'free_text') { el.vorschau.appendChild(knoten('p', '', s.content)); return; }
        var ul = knoten('ul', 'ai-liste');
        (s.rows || []).forEach(function (r) {
          var teile = (s.columns || []).map(function (c) { return r[c.id]; })
                                       .filter(function (x) { return x; });
          if (teile.length) ul.appendChild(knoten('li', 'ai-eintrag', teile.join(' · ')));
        });
        el.vorschau.appendChild(ul);
      });
    });
  }

  // ---- Verdrahtung ---------------------------------------------------------- //

  el.form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    if (window.HermesDiktat && window.HermesDiktat.beschaeftigt()) {
      window.HermesDiktat.stoppe();
      setzeStatus('Die Aufnahme wird abgeschlossen – bitte senden, sobald der Text im Feld steht.');
      return;
    }
    var t = el.text.value.trim();
    if (!t) { el.text.focus(); return; }
    sendeBeitrag(t, null);
  });
  el.text.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { el.form.requestSubmit(); }
  });
  el.tabErkannt.addEventListener('click', function () { zeigeTab(false); });
  el.tabVorschau.addEventListener('click', function () { zeigeTab(true); });
  el.kurz.addEventListener('click', function () {
    var auf = !el.aside.classList.contains('offen');
    el.aside.classList.toggle('offen', auf);
    el.kurz.setAttribute('aria-expanded', auf ? 'true' : 'false');
    zeichneErkannt(ansicht);
  });

  uebernehme(ansicht);
  // Stand vom Server übernommen; standen beim Laden noch Schritte aus (etwa
  // nach einem Abbruch), werden sie jetzt abgearbeitet.
  if (ansicht.ausstehend && ansicht.ausstehend.length) {
    beschaeftigt = true;
    el.senden.disabled = true;
    weiterSchleife(ansicht.ausstehend);
  }
  el.text.focus();
}());
