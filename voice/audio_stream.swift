import Foundation
import AVFoundation

// High-performance continuous audio stream for MAX
// Captures audio continuously from macOS default microphone via AVAudioEngine,
// converts in real-time to 16,000 Hz 16-bit mono PCM, and streams raw bytes to stdout.

signal(SIGINT) { _ in
    fputs("AUDIO_STREAM_STOPPED\n", stderr)
    exit(0)
}
signal(SIGTERM) { _ in
    fputs("AUDIO_STREAM_STOPPED\n", stderr)
    exit(0)
}

let audioEngine = AVAudioEngine()
let inputNode = audioEngine.inputNode
let bus = 0
let inputFormat = inputNode.inputFormat(forBus: bus)

guard inputFormat.sampleRate > 0 && inputFormat.channelCount > 0 else {
    fputs("ERROR: Invalid input audio format.\n", stderr)
    exit(1)
}

// Target format: 16kHz mono 16-bit linear PCM
guard let targetFormat = AVAudioFormat(
    commonFormat: .pcmFormatInt16,
    sampleRate: 16000.0,
    channels: 1,
    interleaved: true
) else {
    fputs("ERROR: Failed to initialize 16kHz target format.\n", stderr)
    exit(1)
}

guard let converter = AVAudioConverter(from: inputFormat, to: targetFormat) else {
    fputs("ERROR: Cannot create AVAudioConverter from \(inputFormat) to \(targetFormat)\n", stderr)
    exit(1)
}

let stdoutHandle = FileHandle.standardOutput

// Install audio tap on input node (buffer size 1024 frames)
inputNode.installTap(onBus: bus, bufferSize: 1024, format: inputFormat) { (inputBuffer, time) in
    // Calculate converted capacity
    let ratio = 16000.0 / inputFormat.sampleRate
    let outputFrameCapacity = AVAudioFrameCount(Double(inputBuffer.frameLength) * ratio + 100)

    guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: outputFrameCapacity) else {
        return
    }

    var error: NSError? = nil
    var inputConsumed = false
    let status = converter.convert(to: outputBuffer, error: &error) { inNumPackets, outStatus in
        if !inputConsumed {
            outStatus.pointee = .haveData
            inputConsumed = true
            return inputBuffer
        } else {
            outStatus.pointee = .noDataNow
            return nil
        }
    }

    if (status == .haveData || status == .inputRanDry) && outputBuffer.frameLength > 0 {
        let byteCount = Int(outputBuffer.frameLength) * 2 // 16-bit = 2 bytes per sample
        if let channelData = outputBuffer.int16ChannelData {
            write(STDOUT_FILENO, channelData[0], byteCount)
        }
    }
}

do {
    try audioEngine.start()
    fputs("AUDIO_STREAM_READY:16000:1:16\n", stderr)
    fflush(stderr)
    RunLoop.current.run()
} catch {
    fputs("ERROR: Failed to start AVAudioEngine: \(error.localizedDescription)\n", stderr)
    exit(1)
}
