import Foundation

enum APIClient {
    // MARK: - Health

    static func health(host: String? = nil) async throws -> [String: String] {
        let base = host.map { "http://\($0):8090" } ?? ServerConfig.baseURL
        var request = URLRequest(url: URL(string: "\(base)/api/health")!)
        request.httpMethod = "GET"

        let (data, response) = try await URLSession.shared.data(for: request)
        if let httpResp = response as? HTTPURLResponse, httpResp.statusCode >= 400 {
            throw NSError(domain: "API", code: httpResp.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "服务器返回错误 (\(httpResp.statusCode))"])
        }
        return try JSONDecoder().decode([String: String].self, from: data)
    }

    // MARK: - Analyze

    static func analyze(audioURL: URL, timeSig: String? = nil) async throws -> AnalysisResult {
        let boundary = UUID().uuidString
        var request = URLRequest(url: URL(string: "\(ServerConfig.baseURL)/api/analyze")!)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120

        let audioData = try Data(contentsOf: audioURL)
        let filename = audioURL.lastPathComponent

        var body = Data()
        // audio 字段
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n".data(using: .utf8)!)
        // time_sig 字段（可选）
        if let ts = timeSig {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"time_sig\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(ts)\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        if let httpResp = response as? HTTPURLResponse, httpResp.statusCode >= 400 {
            if let errJson = try? JSONDecoder().decode([String: String].self, from: data),
               let msg = errJson["error"] {
                throw NSError(domain: "API", code: httpResp.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: msg])
            }
            throw NSError(domain: "API", code: httpResp.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "请求失败 (\(httpResp.statusCode))"])
        }
        return try JSONDecoder().decode(AnalysisResult.self, from: data)
    }

    // MARK: - Search

    static func search(audioURL: URL) async throws -> SearchResponse {
        let boundary = UUID().uuidString
        var request = URLRequest(url: URL(string: "\(ServerConfig.baseURL)/api/search")!)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 90

        let audioData = try Data(contentsOf: audioURL)
        let filename = audioURL.lastPathComponent

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        if let httpResp = response as? HTTPURLResponse, httpResp.statusCode >= 400 {
            if let errJson = try? JSONDecoder().decode([String: String].self, from: data),
               let msg = errJson["error"] {
                throw NSError(domain: "API", code: httpResp.statusCode,
                    userInfo: [NSLocalizedDescriptionKey: msg])
            }
            throw NSError(domain: "API", code: httpResp.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "搜索失败 (\(httpResp.statusCode))"])
        }
        return try JSONDecoder().decode(SearchResponse.self, from: data)
    }
}
