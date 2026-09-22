import Foundation
import AVFoundation

// Native macOS Audio Recorder using AVFoundation
// Usage: max-recorder <output.wav> <duration_seconds>

guard CommandLine.arguments.count >= 2 else {
    print("Usage: max-recorder <output.wav> [duration_seconds]")
    exit(1)
}

let outputPath = CommandLine.arguments[1]
let duration: Double = CommandLine.arguments.count >= 3 ? (Double(CommandLine.arguments[2]) ?? 5.0) : 5.0
let outputURL = URL(fileURLWithPath: outputPath)

let settings: [String: Any] = [
    AVFormatIDKey: Int(kAudioFormatLinearPCM),
    AVSampleRateKey: 16000.0,
    AVNumberOfChannelsKey: 1,
    AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsBigEndianKey: false,
    AVLinearPCMIsFloatKey: false
]

do {
    let recorder = try AVAudioRecorder(url: outputURL, settings: settings)
    recorder.record()
    print("RECORDING_STARTED:\(outputPath):\(duration)s")
    Thread.sleep(forTimeInterval: duration)
    recorder.stop()
    print("RECORDING_FINISHED")
    exit(0)
} catch {
    print("RECORDING_ERROR:\(error.localizedDescription)")
    exit(1)
}
