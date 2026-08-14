export class WebRtcVideoSession {
  constructor(videoElement, sendSignal, onStatus) {
    this.videoElement = videoElement;
    this.sendSignal = sendSignal;
    this.onStatus = onStatus;
    this.peer = null;
  }

  async handleOffer(payload) {
    this.close();
    const peer = new RTCPeerConnection({
      iceServers: [],
      bundlePolicy: "max-bundle",
    });
    this.peer = peer;

    peer.addEventListener("track", (event) => {
      const [stream] = event.streams;
      if (stream) {
        this.videoElement.srcObject = stream;
        this.videoElement.play().catch(() => {});
        this.onStatus("实时视频已连接");
      }
    });

    peer.addEventListener("icecandidate", (event) => {
      if (event.candidate) {
        this.sendSignal("video.ice", {
          candidate: event.candidate.toJSON(),
        });
      }
    });

    peer.addEventListener("connectionstatechange", () => {
      this.onStatus(`视频：${peer.connectionState}`);
    });

    await peer.setRemoteDescription({ type: "offer", sdp: payload.sdp });
    const answer = await peer.createAnswer();
    await peer.setLocalDescription(answer);
    this.sendSignal("video.answer", { sdp: answer.sdp });
  }

  async addIceCandidate(payload) {
    if (this.peer && payload.candidate) {
      await this.peer.addIceCandidate(payload.candidate);
    }
  }

  request() {
    this.sendSignal("video.request", {
      preferredCodec: "H264",
      maxWidth: 1280,
      maxHeight: 720,
      maxFps: 30,
    });
  }

  close() {
    if (this.peer) {
      this.peer.close();
      this.peer = null;
    }
    this.videoElement.srcObject = null;
  }
}
