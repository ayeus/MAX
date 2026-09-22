import Foundation
import AVFoundation

// Native macOS Audio Recorder using AVFoundation with Voice Activity Detection (VAD)
// Usage: max-recorder <output.wav> [duration_seconds] [--vad] [--silence <seconds>] [--threshold <dB>]

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("Usage: max-recorder <output.wav> [duration_seconds] [--vad] [--silence <seconds>] [--threshold <dB>]")
    exit(1)
}

let outputPath = args[1]
var maxDuration: Double = 5.0
var useVAD: Bool = false
var silenceTimeout: Double = 1.0
var explicitThreshold: Float? = nil

var i = 2
while i < args.count {
    let arg = args[i]
    if arg == "--vad" {
        useVAD = true
    } else if arg == "--silence" && i + 1 < args.count {
        i += 1
        silenceTimeout = Double(args[i]) ?? 1.0
    } else if arg == "--threshold" && i + 1 < args.count {
        i += 1
        explicitThreshold = Float(args[i])
    } else if let d = Double(arg) {
        maxDuration = d
    }
    i += 1
}

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
    recorder.isMeteringEnabled = true
    recorder.record()
    print("RECORDING_STARTED:\(outputPath):\(maxDuration)s:vad=\(useVAD)")

    if useVAD {
        let pollInterval: Double = 0.05
        var elapsed: Double = 0.0
        var speechDetected = false
        var silenceDuration: Double = 0.0

        // Calibrate ambient noise floor for 150ms
        var ambientSamples: [Float] = []
        for _ in 0..<3 {
            Thread.sleep(forTimeInterval: 0.05)
            elapsed += 0.05
            recorder.updateMeters()
            ambientSamples.append(recorder.averagePower(forChannel: 0))
        }

        let ambientAverage = ambientSamples.reduce(0.0, +) / Float(ambientSamples.count)
        let dynamicThreshold: Float = min(-25.0, max(-45.0, ambientAverage + 6.0))
        let activeThreshold: Float = explicitThreshold ?? dynamicThreshold

        while elapsed < maxDuration {
            Thread.sleep(forTimeInterval: pollInterval)
            elapsed += pollInterval
            recorder.updateMeters()
            let power = recorder.averagePower(forChannel: 0)

            if power > activeThreshold {
                speechDetected = true
                silenceDuration = 0.0
            } else if speechDetected {
                silenceDuration += pollInterval
                if silenceDuration >= silenceTimeout {
                    // User spoke and then paused for silenceTimeout seconds
                    break
                }
            }
        }
    } else {
        Thread.sleep(forTimeInterval: maxDuration)
    }

    recorder.stop()
    print("RECORDING_FINISHED")
    exit(0)
} catch {
    print("RECORDING_ERROR:\(error.localizedDescription)")
    exit(1)
}
