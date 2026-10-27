// Browser microphone capture only; speech recognition runs on the server.
export class Microphone {
  constructor(onRecording,onState,onError){this.onRecording=onRecording;this.onState=onState;this.onError=onError;this.generation=0;this.recorder=null;this.stream=null;this.timer=null;}
  static supported(){return !!(navigator.mediaDevices?.getUserMedia&&window.MediaRecorder)}
  async start(){
    const token=++this.generation;this.onState('requesting');
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
      if(token!==this.generation){stream.getTracks().forEach(t=>t.stop());return}
      this.stream=stream;const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
      this.recorder=new MediaRecorder(stream,mime?{mimeType:mime,audioBitsPerSecond:64000}:{});const chunks=[];const recorder=this.recorder;
      recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
      recorder.onerror=e=>{if(token===this.generation){this.cancel();this.onError(e.error||Error('The microphone recording failed.'))}};
      recorder.onstop=()=>{if(token!==this.generation)return;this.release();this.onState('idle');this.onRecording(new Blob(chunks,{type:recorder.mimeType}))};
      recorder.start(250);this.onState('recording');this.timer=setTimeout(()=>this.finish(),15000);
    }catch(error){if(token===this.generation){this.release();this.onState('idle');this.onError(error)}}
  }
  finish(){if(this.recorder?.state==='recording')this.recorder.stop()}
  cancel(){this.generation++;this.finish();this.release();this.onState('idle')}
  release(){clearTimeout(this.timer);this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;this.recorder=null;}
}

export function audioBase64(blob){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob)})}
