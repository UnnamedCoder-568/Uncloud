// Listening, natively, so a conversation does not wait for a transcript.
//
// The browser's recorder can only hand over a finished clip: you stop talking,
// the clip is uploaded, a model loads, and only then does anything know what
// you said. That is a second or more of silence in a conversation, every turn,
// and it is spent on work that could have happened while you were speaking.
//
// This transcribes as the words arrive, on the device, using Apple's own
// recogniser — nothing is sent anywhere — and says when a turn has ended. By
// the time you stop, the text is already there.
//
// It speaks one JSON object per line on stdout, and nothing else:
//
//     {"event":"ready","locale":"en-US"}
//     {"event":"partial","text":"what is the"}
//     {"event":"final","text":"What is the weather"}
//     {"event":"endOfTurn","text":"What is the weather like today?"}
//     {"event":"error","message":"..."}
//
// Commands arrive on stdin, one word per line: `stop` ends the turn now,
// `quit` exits. Anything else is ignored rather than guessed at.

import AVFoundation
import Foundation
import Speech

// MARK: - Protocol

/// stdout carries the protocol and nothing else; every other message goes to
/// stderr, where it can be logged without corrupting what the app parses.
func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload),
          let line = String(data: data, encoding: .utf8) else { return }
    print(line)
    fflush(stdout)
}

func note(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

// MARK: - Turn ending
//
// Apple reports a result as final when it is confident the phrase is complete,
// but a speaker who pauses mid-thought would be cut off by that alone. A turn
// ends when the transcript has stopped changing for long enough — measured
// from the last change, not from the last sound, so thinking noises do not
// hold the line open.

let silenceSeconds = ProcessInfo.processInfo.environment["UNCLOUD_TURN_SILENCE"]
    .flatMap(Double.init) ?? 0.55

actor Turn {
    /// Sentences the recogniser has settled on, joined. A final result covers
    /// only the phrase it ended, so keeping just the latest one loses
    /// everything said before it — a long question arrived as its last clause.
    private var committed = ""
    /// The phrase still being spoken, replaced with every partial result.
    private var volatileText = ""
    private var changedAt = Date()
    private var ended = false

    private var text: String {
        (committed + volatileText).trimmingCharacters(in: .whitespaces)
    }

    func update(_ latest: String, isFinal: Bool) {
        if isFinal {
            committed += latest
            volatileText = ""
            changedAt = Date()
            ended = false
        } else if latest != volatileText {
            volatileText = latest
            changedAt = Date()
            ended = false
        }
    }

    /// The turn's text, if it has been quiet long enough to be over.
    func finishedTurn(now: Date = Date()) -> String? {
        guard !ended, !text.isEmpty, now.timeIntervalSince(changedAt) >= silenceSeconds
        else { return nil }
        ended = true
        return text
    }

    func reset() {
        committed = ""
        volatileText = ""
        changedAt = Date()
        ended = false
    }

    func current() -> String { text }
}

// MARK: - Recognition

@available(macOS 26.0, *)
final class Listener {
    private let transcriber: SpeechTranscriber
    private let analyzer: SpeechAnalyzer
    private let engine = AVAudioEngine()
    private var stream: AsyncStream<AnalyzerInput>.Continuation?
    private let turn = Turn()

    private let locale: Locale

    init(locale: Locale) {
        self.locale = locale
        // Volatile results are the partial ones: what makes this feel immediate
        // rather than merely fast.
        transcriber = SpeechTranscriber(locale: locale,
                                        transcriptionOptions: [],
                                        reportingOptions: [.volatileResults],
                                        attributeOptions: [])
        analyzer = SpeechAnalyzer(modules: [transcriber])
    }

    /// Ask for the language's assets if they are not on the machine yet. They
    /// are Apple's, they install once, and the request is what stops the first
    /// sentence failing on a fresh Mac.
    static func install(for transcriber: SpeechTranscriber) async throws {
        if let request = try await AssetInventory.assetInstallationRequest(
            supporting: [transcriber]) {
            note("installing speech assets…")
            try await request.downloadAndInstall()
        }
    }

    func run(from file: URL?) async throws {
        try await Listener.install(for: transcriber)
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(
            compatibleWith: [transcriber]) else {
            throw Failure("This Mac has no audio format the recogniser accepts.")
        }

        let (inputs, continuation) = AsyncStream<AnalyzerInput>.makeStream()
        stream = continuation
        try await analyzer.start(inputSequence: inputs)
        emit(["event": "ready", "locale": locale.identifier])

        let results = Task { [transcriber, turn] in
            do {
                for try await result in transcriber.results {
                    let text = String(result.text.characters)
                    await turn.update(text, isFinal: result.isFinal)
                    emit(["event": result.isFinal ? "final" : "partial", "text": text])
                }
            } catch {
                emit(["event": "error", "message": "\(error)"])
            }
        }

        if let file {
            try await feed(file: file, format: format)
        } else {
            try startMicrophone(format: format)
        }

        // The turn ends when the words stop changing. Checked here rather than
        // in the results loop because the last word arriving is exactly when
        // nothing more arrives to trigger a check.
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 100_000_000)
            if let ended = await turn.finishedTurn() {
                emit(["event": "endOfTurn", "text": ended])
                await turn.reset()
            }
        }
        results.cancel()
    }

    private func startMicrophone(format: AVAudioFormat) throws {
        let input = engine.inputNode
        let native = input.outputFormat(forBus: 0)
        let converter = AVAudioConverter(from: native, to: format)
        input.installTap(onBus: 0, bufferSize: 2048, format: native) { [weak self] buffer, _ in
            guard let self else { return }
            guard let converter,
                  let converted = AVAudioPCMBuffer(
                      pcmFormat: format,
                      frameCapacity: AVAudioFrameCount(
                          Double(buffer.frameLength) * format.sampleRate / native.sampleRate) + 64)
            else {
                self.stream?.yield(AnalyzerInput(buffer: buffer))
                return
            }
            var supplied = false
            var error: NSError?
            converter.convert(to: converted, error: &error) { _, status in
                if supplied {
                    status.pointee = .noDataNow
                    return nil
                }
                supplied = true
                status.pointee = .haveData
                return buffer
            }
            if error == nil, converted.frameLength > 0 {
                self.stream?.yield(AnalyzerInput(buffer: converted))
            }
        }
        engine.prepare()
        try engine.start()
    }

    /// Reading a file instead of the microphone. This is how the helper is
    /// tested without a person in the room.
    private func feed(file url: URL, format: AVAudioFormat) async throws {
        let audio = try AVAudioFile(forReading: url)
        let converter = AVAudioConverter(from: audio.processingFormat, to: format)
        let chunk: AVAudioFrameCount = 4096
        // Read to the end of the file, not past it: reading beyond the last
        // frame throws rather than returning nothing, which arrives as an
        // "end of file" error in the middle of a perfectly good transcript.
        while audio.framePosition < audio.length {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: audio.processingFormat,
                                                frameCapacity: chunk) else { break }
            let remaining = AVAudioFrameCount(min(Int64(chunk), audio.length - audio.framePosition))
            try audio.read(into: buffer, frameCount: remaining)
            if buffer.frameLength == 0 { break }
            if let converter,
               let converted = AVAudioPCMBuffer(
                   pcmFormat: format,
                   frameCapacity: AVAudioFrameCount(
                       Double(buffer.frameLength) * format.sampleRate
                           / audio.processingFormat.sampleRate) + 64) {
                var supplied = false
                var error: NSError?
                converter.convert(to: converted, error: &error) { _, status in
                    if supplied { status.pointee = .noDataNow; return nil }
                    supplied = true
                    status.pointee = .haveData
                    return buffer
                }
                if error == nil, converted.frameLength > 0 {
                    stream?.yield(AnalyzerInput(buffer: converted))
                }
            } else {
                stream?.yield(AnalyzerInput(buffer: buffer))
            }
        }
        stream?.finish()
        try await analyzer.finalizeAndFinishThroughEndOfInput()
    }

    func endTurnNow() async {
        let text = await turn.current()
        if !text.isEmpty {
            emit(["event": "endOfTurn", "text": text])
            await turn.reset()
        }
    }

    func stop() {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        stream?.finish()
    }
}

struct Failure: Error, CustomStringConvertible {
    let description: String
    init(_ description: String) { self.description = description }
}

// MARK: - Entry

@main
struct Main {
    static func main() async {
        let arguments = CommandLine.arguments
        let file = arguments.firstIndex(of: "--file").map { URL(fileURLWithPath: arguments[$0 + 1]) }
        let locale = arguments.firstIndex(of: "--locale").map { Locale(identifier: arguments[$0 + 1]) }
            ?? Locale.current

        guard #available(macOS 26.0, *) else {
            emit(["event": "error", "message": "This needs macOS 26 or newer."])
            exit(2)
        }

        // Permission is the app's to hold; this asks so a refusal is a message
        // rather than a silent empty transcript. Only for the microphone:
        // transcribing a file the user already has needs no such permission,
        // and asking for it there would put a dialog in front of somebody who
        // is not being listened to.
        if file == nil {
            let granted = await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { status in
                    continuation.resume(returning: status == .authorized)
                }
            }
            guard granted else {
                emit(["event": "error", "message": "Speech recognition was not allowed."])
                exit(3)
            }
        }

        let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale)
        let listener = Listener(locale: supported ?? Locale(identifier: "en-US"))

        // Commands from the app: end this turn, or leave.
        Task.detached {
            while let line = readLine(strippingNewline: true) {
                switch line.trimmingCharacters(in: .whitespaces) {
                case "stop": await listener.endTurnNow()
                case "quit": listener.stop(); exit(0)
                default: break
                }
            }
            listener.stop()
            exit(0)
        }

        do {
            try await listener.run(from: file)
        } catch {
            emit(["event": "error", "message": "\(error)"])
            exit(1)
        }
    }
}
