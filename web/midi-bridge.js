'use strict';
// Translate Wine's original MIDI output messages into browser audio.
// Music selection, timing, notes and volume still come from the original program.
window.Rich4Midi = (() => {
  let synth;
  let count = 0;
  function unlock() {
    if (!synth) synth = new WebAudioTinySynth({quality:1, useReverb:1, voices:64});
    synth.getAudioContext().resume().catch(console.warn);
  }
  function silence() {
    if (!synth) return;
    for (let channel = 0; channel < 16; channel++) synth.send([0xb0 | channel, 120, 0]);
  }
  function onLog(text) {
    const message = text.match(/trace:winmm:midiOutShortMsg\s*\([^,]+,\s*(?:0x)?([a-f\d]{8})\s*\)/i);
    if (message && synth) {
      const packed = parseInt(message[1],16);
      synth.send([packed & 255, (packed >>> 8) & 127, (packed >>> 16) & 127]);
      count++;
    }
    if (/trace:winmm:midiOut(?:Reset|Close)\s*\(/i.test(text)) silence();
    return /:trace:winmm:/.test(text);
  }
  return {unlock, silence, onLog, get count() {return count;}};
})();
