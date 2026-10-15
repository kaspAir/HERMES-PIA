// Spracheingabe für HERMES PIA – gemeinsam für beide Interview-Oberflächen.
//
// Unverändert aus interview.html übernommen (dort lag sie inline) und um eine
// kleine Schnittstelle ergänzt: die adaptive Oberfläche schickt Beiträge per
// fetch statt per Formular und muss vorher fragen können, ob noch eine
// Aufnahme läuft oder Segmente transkribiert werden.
//
// Zwei Varianten:
//  A) Server-STT (bevorzugt, wenn konfiguriert): Aufnahme über ein in HERMES PIA
//     WÄHLBARES Mikrofon (getUserMedia) – es wird ausschliesslich dieses Mikrofon
//     aufgenommen, nie das Meeting-/Systemaudio. Segmente gehen Base64-in-JSON an
//     /transcribe (Text-Body -> proxy-verträglich wie normale Formular-POSTs).
//  B) Fallback: Browser-Spracherkennung (Web Speech API, Standard-Mikrofon).
(function () {
  var zustand = { beschaeftigt: function () { return false; }, stoppe: function () {} };
  window.HermesDiktat = zustand;

  var btn      = document.getElementById('voice-btn');
  var textarea = document.getElementById('answer-text');
  var statusEl = document.getElementById('voice-status');
  var micSel   = document.getElementById('mic-select');
  if (!btn || !textarea) return;

  function setStatus(t) { if (statusEl) statusEl.textContent = t; }
  function setUiRecording(on) {
    btn.textContent = on ? '⏹ Aufnahme stoppen' : '🎤 Sprechen';
    btn.classList.toggle('recording', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
  }
  function append(text) {
    if (!text) return;
    textarea.value = (textarea.value ? textarea.value.trim() + ' ' : '') + text;
    textarea.dispatchEvent(new Event('input'));
  }

  var canRecord = navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
                  typeof MediaRecorder !== 'undefined';
  if (btn.dataset.stt === '1' && canRecord) { initMicRecorder(); }
  else { initWebSpeech(); }

  // ---- Variante A: wählbares Mikrofon + Server-Transkription ---------- //
  function initMicRecorder() {
    var endpoint = btn.dataset.endpoint;
    var SEG_MS = 12000;                       // Segmentlänge: echtzeitnah, kleine Bodies
    var NACHLAUF_MS = 1500;                   // Stille nach dem Stopp (siehe stopRecording)
    var stream = null, recorder = null, timer = null, nachlauf = null, running = false;

    if (micSel) {
      micSel.style.display = '';
      refreshDevices();
      if (navigator.mediaDevices.addEventListener) {
        navigator.mediaDevices.addEventListener('devicechange', refreshDevices);
      }
      micSel.addEventListener('change', function () {
        try { localStorage.setItem('hp-mic-id', micSel.value); } catch (e) {}
        if (running) { stopRecording(); startRecording(); }   // laufend aufs neue Gerät wechseln
      });
    }

    function savedMicId() {
      try { return localStorage.getItem('hp-mic-id') || ''; } catch (e) { return ''; }
    }

    function refreshDevices() {
      if (!micSel) return;
      navigator.mediaDevices.enumerateDevices().then(function (devs) {
        var saved = savedMicId();
        micSel.innerHTML = '';
        var def = document.createElement('option');
        def.value = '';
        def.textContent = 'Standard-Mikrofon';
        micSel.appendChild(def);
        var i = 0;
        devs.forEach(function (d) {
          if (d.kind !== 'audioinput' || !d.deviceId || d.deviceId === 'default') return;
          i += 1;
          var o = document.createElement('option');
          o.value = d.deviceId;
          o.textContent = d.label || ('Mikrofon ' + i);
          micSel.appendChild(o);
        });
        micSel.value = saved;
        if (micSel.selectedIndex < 0) micSel.value = '';
      }).catch(function () {});
    }

    // Uploads SERIALISIEREN: immer nur ein Transkriptions-Request gleichzeitig;
    // Backlog begrenzen, damit es echtzeitnah bleibt.
    var sendQueue = [], sending = false;

    function toB64(blob) {
      return new Promise(function (resolve, reject) {
        var fr = new FileReader();
        fr.onload  = function () { resolve(String(fr.result).split(',')[1] || ''); };
        fr.onerror = reject;
        fr.readAsDataURL(blob);
      });
    }

    function enqueue(blob) {
      sendQueue.push(blob);
      while (sendQueue.length > 3) sendQueue.shift();
      pump();
    }

    function pump() {
      if (sending || !sendQueue.length) {
        if (!sending && !sendQueue.length && !running) {
          setStatus('Transkription abgeschlossen – der Text steht im Antwortfeld.');
        }
        return;
      }
      sending = true;
      var blob = sendQueue.shift();
      toB64(blob).then(function (b64) {
        return fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ audio: b64, mime: blob.type || 'audio/webm' })
        });
      })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.text) append(d.text);
        if (d.error) setStatus('Transkription: ' + d.error);
        else if (running) setStatus('Aufnahme läuft – nur das gewählte Mikrofon wird erfasst …');
      })
      .catch(function () { setStatus('Transkription gerade verzögert – läuft weiter …'); })
      .then(function () { sending = false; pump(); });
    }

    function recordSegment() {
      if (!running || !stream) return;
      var chunks = [];
      try { recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' }); }
      catch (e) { recorder = new MediaRecorder(stream); }
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        if (chunks.length) enqueue(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }));
        if (running) recordSegment();          // nahtlos das nächste Segment
      };
      recorder.start();
      timer = setTimeout(function () {
        if (recorder && recorder.state !== 'inactive') recorder.stop();
      }, SEG_MS);
    }

    function startRecording() {
      // Laeuft noch ein Nachlauf vom letzten Stopp, jetzt sauber abschliessen –
      // sonst wuerde dessen Timer gleich den frisch geoeffneten Stream schliessen.
      if (nachlauf) hardStop();
      var id = savedMicId();
      var constraints = { audio: id ? { deviceId: { exact: id } } : true };
      navigator.mediaDevices.getUserMedia(constraints).catch(function () {
        // Gewähltes Gerät nicht (mehr) verfügbar -> Standard-Mikrofon versuchen.
        setStatus('Gewähltes Mikrofon nicht verfügbar – Standard-Mikrofon wird verwendet.');
        return navigator.mediaDevices.getUserMedia({ audio: true });
      }).then(function (s) {
        stream = s;
        s.getAudioTracks().forEach(function (t) { t.onended = stopAll; });
        running = true;
        setUiRecording(true);
        setStatus('Aufnahme läuft – nur das gewählte Mikrofon wird erfasst …');
        refreshDevices();                      // nach Freigabe sind Gerätenamen sichtbar
        recordSegment();
      }).catch(function () {
        setStatus('Mikrofonzugriff nicht möglich – bitte Berechtigung im Browser erteilen.');
      });
    }

    function stopRecording() {
      // Sanft stoppen: das letzte Segment wird noch enqueued und die
      // Warteschlange fertig transkribiert – kein Textverlust.
      running = false;
      if (timer) clearTimeout(timer);
      // NACHLAUF: Wer auf "Stopp" klickt, tut das direkt nach dem letzten Wort.
      // Die Spracherkennung braucht danach aber noch etwas Stille, sonst wird
      // das Wortende abgeschnitten. Diese Stille nimmt die Anwendung selbst auf –
      // niemand soll bewusst nachschweigen muessen.
      if (nachlauf) clearTimeout(nachlauf);
      nachlauf = setTimeout(hardStop, NACHLAUF_MS);
      setUiRecording(false);
      if (sending || sendQueue.length) {
        setStatus('Aufnahme gestoppt – die Transkription wird abgeschlossen …');
      } else {
        setStatus('');
      }
    }

    function hardStop() {
      // Recorder und Mikrofon wirklich schliessen. Das laufende Segment landet
      // ueber recorder.onstop noch in der Warteschlange – kein Textverlust.
      if (nachlauf) { clearTimeout(nachlauf); nachlauf = null; }
      if (recorder && recorder.state !== 'inactive') recorder.stop();
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null;
    }

    function stopAll() {
      // Hart stoppen (z.B. Mikrofon weggefallen): Backlog verwerfen. Ein Nachlauf
      // brächte hier nichts, das Mikrofon liefert ohnehin nichts mehr.
      sendQueue = [];
      running = false;
      if (timer) clearTimeout(timer);
      hardStop();
      setUiRecording(false);
      setStatus('');
    }

    btn.addEventListener('click', function () {
      if (running) { stopRecording(); } else { startRecording(); }
    });

    zustand.beschaeftigt = function () {
      return running || !!nachlauf || sending || sendQueue.length > 0;
    };
    zustand.stoppe = function () { if (running) stopRecording(); };

    // „Weiter" während Aufnahme/Transkription: NICHT abschicken, sondern sauber
    // stoppen bzw. auf die letzten Segmente warten – sonst geht die Antwort mit
    // halbem Text ab und der Abschnitt gilt als beantwortet.
    var form = textarea.form;
    if (form) {
      form.addEventListener('submit', function (e) {
        if (running) {
          e.preventDefault();
          stopRecording();
          setStatus('Aufnahme gestoppt – bitte kurz warten, bis der Text im Feld steht, '
                    + 'und dann erneut auf «Weiter» klicken.');
        } else if (nachlauf || sending || sendQueue.length) {
          e.preventDefault();
          setStatus('Die Transkription läuft noch – bitte gleich erneut auf «Weiter» klicken.');
        }
      });
    }
  }

  // ---- Variante B: Browser-Spracherkennung (Fallback) ------------------ //
  function initWebSpeech() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { btn.style.display = 'none'; return; }

    var recognition = new SpeechRecognition();
    recognition.lang            = 'de-CH';
    recognition.continuous      = true;
    recognition.interimResults  = true;
    recognition.maxAlternatives = 1;

    var active = false, finalTranscript = '', interimText = '';

    function render() { textarea.value = finalTranscript + interimText; }

    btn.addEventListener('click', function () {
      if (!active) {
        finalTranscript = textarea.value.trim();
        if (finalTranscript) finalTranscript += ' ';
        interimText = '';
        active = true;
        recognition.start();
      } else {
        active = false;
        recognition.stop();
      }
    });

    zustand.beschaeftigt = function () { return active; };
    zustand.stoppe = function () { if (active) { active = false; recognition.stop(); } };

    recognition.onstart  = function () {
      setUiRecording(true);
      setStatus('Aufnahme läuft – bitte sprechen …');
    };
    recognition.onresult = function (event) {
      interimText = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var t = event.results[i][0].transcript;
        if (event.results[i].isFinal) { finalTranscript += t + ' '; }
        else                          { interimText = t; }
      }
      render();
    };
    recognition.onend = function () {
      if (active) { recognition.start(); }
      else {
        finalTranscript += interimText; interimText = '';
        render(); setUiRecording(false); setStatus('');
      }
    };
    recognition.onerror = function (e) {
      if (e.error === 'no-speech') return;
      active = false; setUiRecording(false);
      setStatus('Fehler: ' + e.error);
    };
  }
}());
