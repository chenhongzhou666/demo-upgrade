import Foundation

struct ChordResult: Codable, Equatable {
    let symbol: String
    let degree: String
    let function: String
    let inversion: Int
    let warning: String?
}

struct TimbreResult: Codable, Equatable {
    let primary: String
    let distribution: [String: Int]
}

struct FilePaths: Codable, Equatable {
    let midi: String
    let musicxml: String
}

struct AnalysisResult: Codable, Equatable {
    let keyName: String
    let mode: String
    let bpm: Double
    let timeSig: String
    let chords: [ChordResult]
    let jianpu: String
    let timbre: TimbreResult
    let files: FilePaths
    let musicxmlData: String?

    enum CodingKeys: String, CodingKey {
        case keyName = "key_name"
        case mode
        case bpm
        case timeSig = "time_sig"
        case chords
        case jianpu
        case timbre
        case files
        case musicxmlData = "musicxml_data"
    }

    var keyDisplay: String {
        "\(keyName) \(mode == "major" ? "大调" : "小调")"
    }

    var bpmDisplay: String {
        String(format: "%.0f BPM", bpm)
    }

    var chordProgression: String {
        guard !chords.isEmpty else { return "无" }
        return chords.map { chord in
            var s = "\(chord.symbol)"
            if !chord.function.isEmpty {
                s += "(\(chord.function))"
            }
            return s
        }.joined(separator: " → ")
    }

    var hasWarning: Bool {
        chords.contains { $0.warning != nil && !$0.warning!.isEmpty }
    }

    var warnings: [String] {
        chords.compactMap { $0.warning }.filter { !$0.isEmpty }
    }
}

// MARK: - 查重搜索

struct SearchTrack: Codable, Identifiable {
    let id: String
    let title: String
    let composer: String
    let keyName: String

    enum CodingKeys: String, CodingKey {
        case id, title, composer
        case keyName = "key_name"
    }
}

struct SearchResultItem: Codable, Identifiable {
    let track: SearchTrack
    let matchCount: Int
    let containment: Double
    let jaccard: Double

    enum CodingKeys: String, CodingKey {
        case track
        case matchCount = "match_count"
        case containment, jaccard
    }

    var id: String { track.id }

    /// 0-100 相似度 (取 containment 和 jaccard 的加权组合)
    var similarityPercent: Int {
        Int((containment * 0.6 + jaccard * 0.4) * 100)
    }
}

struct SearchResponse: Codable {
    let query: SearchQuery
    let results: [SearchResultItem]
    let librarySize: Int

    enum CodingKeys: String, CodingKey {
        case query, results
        case librarySize = "library_size"
    }
}

struct SearchQuery: Codable {
    let totalNotes: Int
    let hashCount: Int
    let ngramSize: Int

    enum CodingKeys: String, CodingKey {
        case totalNotes = "total_notes"
        case hashCount = "hash_count"
        case ngramSize = "ngram_size"
    }
}
