import Foundation

@MainActor
class ServerManager: ObservableObject {
    enum Status: Equatable {
        case stopped
        case starting
        case running
        case failed(String)
    }

    @Published var status: Status = .stopped
    let port = 8090

    #if os(macOS)
    // MARK: - macOS: 本地 Process() 启动 Go 二进制

    private var process: Process?

    func start() {
        if case .running = status { return }
        if case .starting = status { return }

        status = .starting

        var foundPath: String?
        var searchPaths: [String] = []

        if let rp = Bundle.main.resourcePath {
            searchPaths.append(rp + "/demo-upgrade-server")
        }
        if let ep = Bundle.main.executablePath {
            let exeDir = (ep as NSString).deletingLastPathComponent
            searchPaths.append(exeDir + "/../Resources/demo-upgrade-server")
        }
        searchPaths.append(NSHomeDirectory() + "/Desktop/Demo独自升级/server/demo-upgrade-server")

        for p in searchPaths {
            if FileManager.default.fileExists(atPath: p) {
                foundPath = p
                break
            }
        }

        guard let path = foundPath else {
            status = .failed("找不到服务器程序 (demo-upgrade-server)，请先编译后端")
            return
        }

        let serverProc = Process()
        serverProc.executableURL = URL(fileURLWithPath: path)

        var env = ProcessInfo.processInfo.environment
        env["TZ"] = "Asia/Shanghai"
        serverProc.environment = env

        let outPipe = Pipe()
        serverProc.standardOutput = outPipe
        serverProc.standardError = outPipe

        do {
            try serverProc.run()
            process = serverProc
        } catch {
            status = .failed("启动服务器失败: \(error.localizedDescription)")
            return
        }

        checkHealthAsync(proc: serverProc)
    }

    private func checkHealthAsync(proc: Process) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            self?.pollHealth(proc: proc, until: Date().addingTimeInterval(5))
        }
    }

    private func pollHealth(proc: Process, until deadline: Date) {
        guard Date() < deadline, proc.isRunning else {
            if proc.isRunning { status = .failed("服务器启动超时") }
            return
        }

        var request = URLRequest(url: URL(string: "http://localhost:\(port)/api/health")!)
        request.httpMethod = "GET"
        URLSession.shared.dataTask(with: request) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                    self?.status = .running
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                        self?.pollHealth(proc: proc, until: deadline)
                    }
                }
            }
        }.resume()
    }

    func stop() {
        process?.terminate()
        process = nil
        status = .stopped
    }

    #else
    // MARK: - iOS/iPadOS: 远程连接模式（不启子进程）

    func connect(to host: String) {
        status = .starting

        let addr = "http://\(host):\(port)"
        var request = URLRequest(url: URL(string: "\(addr)/api/health")!)
        request.httpMethod = "GET"
        request.timeoutInterval = 3

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            DispatchQueue.main.async {
                if let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 {
                    self?.status = .running
                } else {
                    let reason = error?.localizedDescription ?? "无法连接到 \(addr)"
                    self?.status = .failed(reason)
                }
            }
        }.resume()
    }

    func disconnect() {
        status = .stopped
    }

    #endif
}
