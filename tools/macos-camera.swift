// A bounded, video-only capture app launched in the Mac's desktop session.
import AppKit
import AVFoundation
import CoreImage
import ImageIO
import UniformTypeIdentifiers

final class CameraObserver: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let queue = DispatchQueue(label: "org.gameshellneo.camera")
    let session = AVCaptureSession()
    let context = CIContext()
    let destination: URL
    let action: String
    let seconds: Double
    let fps: Double
    let cameraName: String
    var finished = false
    var frames: [[String: Any]] = []
    var firstSample: Double?
    var lastFrame = -Double.infinity
    var deadline: DispatchSourceTimer?
    var result: [String: Any] = ["schema": 1, "success": false]

    init(destination: URL, action: String, seconds: Double, fps: Double, cameraName: String) {
        self.destination = destination
        self.action = action
        self.seconds = seconds
        self.fps = fps
        self.cameraName = cameraName
        super.init()
    }

    func timestamp() -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.string(from: Date())
    }

    func authorization() -> String {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: return "authorized"
        case .denied: return "denied"
        case .restricted: return "restricted"
        case .notDetermined: return "notDetermined"
        @unknown default: return "unknown"
        }
    }

    func finish(_ error: String? = nil) {
        guard !finished else { return }
        finished = true
        deadline?.cancel()
        // Finish after the sample callback returns before stopping the session.
        queue.async { self.complete(error) }
    }

    func complete(_ error: String?) {
        if session.isRunning { session.stopRunning() }
        result["ended_utc"] = timestamp()
        result["authorization"] = authorization()
        result["frames"] = frames
        result["camera_stopped"] = !session.isRunning
        result["success"] = error == nil
        if let error = error { result["error"] = error }
        do {
            let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: destination.appendingPathComponent("result.json"), options: .atomic)
        } catch {
            fputs("Could not save camera result: \(error)\n", stderr)
        }
        DispatchQueue.main.async { NSApplication.shared.terminate(nil) }
    }

    func start() {
        queue.async {
            self.result["action"] = self.action
            self.result["started_utc"] = self.timestamp()
            self.result["requested_seconds"] = self.seconds
            self.result["requested_fps"] = self.fps
            self.result["authorization"] = self.authorization()
            let timer = DispatchSource.makeTimerSource(queue: self.queue)
            timer.schedule(deadline: .now() + (self.action == "authorize" ? 120 : self.seconds + 20))
            timer.setEventHandler { self.finish("Camera operation timed out") }
            self.deadline = timer
            timer.resume()
            if self.action == "status" {
                self.finish()
            } else if self.authorization() == "notDetermined" {
                DispatchQueue.main.async {
                    NSApplication.shared.activate(ignoringOtherApps: true)
                    AVCaptureDevice.requestAccess(for: .video) { granted in
                        self.queue.async {
                            if granted { self.authorized() }
                            else { self.finish("Camera access was not granted") }
                        }
                    }
                }
            } else if self.authorization() == "authorized" {
                self.authorized()
            } else {
                self.finish("Enable camera access for GameShellNeo Camera in macOS System Settings")
            }
        }
    }

    func authorized() {
        guard !finished else { return }
        if action == "authorize" { finish(); return }
        let discovery = AVCaptureDevice.DiscoverySession(deviceTypes: [.builtInWideAngleCamera], mediaType: .video, position: .unspecified)
        guard let camera = discovery.devices.first(where: { $0.localizedName == cameraName }) else {
            finish("Requested camera was not found: \(cameraName)"); return
        }
        result["camera_name"] = camera.localizedName
        result["camera_id"] = camera.uniqueID
        do {
            let input = try AVCaptureDeviceInput(device: camera)
            let output = AVCaptureVideoDataOutput()
            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            output.setSampleBufferDelegate(self, queue: queue)
            session.beginConfiguration()
            if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
            guard session.canAddInput(input), session.canAddOutput(output) else {
                session.commitConfiguration()
                finish("Camera session cannot accept video input/output"); return
            }
            session.addInput(input)
            session.addOutput(output)
            session.commitConfiguration()
            result["session_start_requested_utc"] = timestamp()
            session.startRunning()
            // The main-thread watchdog also bounds a blocked startRunning call.
        } catch { finish("Camera setup failed: \(error)") }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard !finished else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if firstSample == nil {
            firstSample = now
            result["first_sample_utc"] = timestamp()
        }
        // Let auto-exposure settle before exporting a still or sequence.
        let elapsed = now - firstSample! - 1.5
        guard elapsed >= 0 else { return }
        if seconds > 0 && elapsed >= seconds {
            finish(frames.isEmpty ? "No camera images were saved" : nil); return
        }
        guard now - lastFrame >= 1.0 / fps else { return }
        guard let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: buffer)
        guard let rendered = context.createCGImage(image, from: image.extent) else {
            finish("Could not render camera frame"); return
        }
        let name = String(format: "frame-%06d.jpg", frames.count + 1)
        let path = destination.appendingPathComponent(name)
        guard let writer = CGImageDestinationCreateWithURL(path as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
            finish("Could not create JPEG output"); return
        }
        CGImageDestinationAddImage(writer, rendered, [kCGImageDestinationLossyCompressionQuality: 0.85] as CFDictionary)
        guard CGImageDestinationFinalize(writer) else { finish("Could not save JPEG"); return }
        frames.append(["file": name, "received_utc": timestamp(),
                       "received_uptime_seconds": now,
                       "sample_pts_seconds": CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds,
                       "width": rendered.width, "height": rendered.height])
        if frames.count == 1 {
            do {
                let ready: [String: Any] = ["schema": 1, "camera_name": cameraName,
                                            "first_exported_frame": frames[0]]
                let data = try JSONSerialization.data(withJSONObject: ready, options: [.prettyPrinted, .sortedKeys])
                try data.write(to: destination.appendingPathComponent("ready.json"), options: .atomic)
            } catch { finish("Could not save camera readiness: \(error)"); return }
        }
        lastFrame = now
        if seconds == 0 { finish() }
    }
}

let args = CommandLine.arguments
guard args.count == 7, ["status", "authorize", "capture"].contains(args[1]),
      let seconds = Double(args[3]), seconds.isFinite, seconds >= 0, seconds <= 300,
      let fps = Double(args[4]), fps.isFinite, fps >= 1, fps <= 5,
      args[6] == "video-only" else { fatalError("Invalid camera arguments") }
let destination = URL(fileURLWithPath: args[2], isDirectory: true)
guard FileManager.default.fileExists(atPath: destination.path) else { fatalError("Missing capture directory") }
let observer = CameraObserver(destination: destination, action: args[1], seconds: seconds, fps: fps, cameraName: args[5])
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
// A main-thread watchdog also bounds a stalled AVCaptureSession startup.
DispatchQueue.main.asyncAfter(deadline: .now() + (args[1] == "authorize" ? 125 : seconds + 25)) { exit(124) }
observer.start()
app.run()
