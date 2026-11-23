const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const requests = [];
let decoded = 0;
const sandbox = {
  window: {},
  fetch: async url => {
    requests.push(url);
    return {ok: true, arrayBuffer: async () => new ArrayBuffer(8)};
  },
};
vm.runInNewContext(fs.readFileSync('src/studio/static/sampled-audio.js', 'utf8'), sandbox);
const audio = {decodeAudioData: async () => {decoded++; return {};}};
(async () => {
  const samples = sandbox.window.StudioSamples;
  await Promise.all([samples.load(audio, 'Piano', [60,60,64]), samples.load(audio, 'Piano', [60,67])]);
  assert.equal(requests.length, 3, 'Concurrent requests must share downloads');
  assert.equal(decoded, 3, 'Only requested notes should be decoded');
  await samples.load(audio, 'Piano', [60,64,67]);
  assert.equal(requests.length, 3, 'Repeated playback should use decoded cache');
  await samples.load(audio, 'Flute', [60]);
  assert.equal(decoded, 4, 'Different instruments need distinct samples');
  await samples.load(audio, 'Piano', [0,127]);
  assert.ok(requests.includes('/sounds/Piano/21.mp3'));
  assert.ok(requests.includes('/sounds/Piano/108.mp3'));
  let source;
  const gain = {gain: {setValueAtTime(){},linearRampToValueAtTime(){}},connect(){}};
  audio.createGain=()=>gain;
  audio.createBufferSource=()=>source={playbackRate:{},connect(){},start(){},stop(){}};
  samples.play(audio,{},new Set(),65,1,0,'Piano',1);
  assert.equal(source.playbackRate.value,2**(1/12),'Use the nearest decoded key to sound the requested pitch');
  await samples.load(audio,'Piano',[65]);
  samples.play(audio,{},new Set(),65,1,0,'Piano',1);
  assert.equal(source.playbackRate.value,1,'Switch to the exact sample when decoded');
  console.log('Sample loading: subset selection, concurrent deduplication, caching and range boundaries passed.');
})().catch(error => {console.error(error);process.exitCode = 1;});
