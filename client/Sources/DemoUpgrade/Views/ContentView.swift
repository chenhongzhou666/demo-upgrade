import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var server: ServerManager

    @State private var analysisState: AnalysisState = .idle
    @State private var result: AnalysisResult?
    @State private var errorMessage: String?
    @State private var isDropTargeted = false
    @State private var showFileImporter = false
    @State private var showSheetMusic = false

    #if os(iOS)
    @State private var serverHost: String = ServerConfig.host
    @State private var isConnecting = false
    #endif

    enum AnalysisState {
        case idle
        case uploading
        case analyzing
        case done
        case error
    }

    var body: some View {
        VStack(spacing: 0) {
            titleBar

            Divider()
                .padding(.horizontal, 24)

            #if os(iOS)
            // iPad: 服务器连接栏
            serverConnectBar
            Divider().padding(.horizontal, 24)
            #endif

            Spacer(minLength: 16)

            switch analysisState {
            case .idle:
                dropZoneView
            case .uploading, .analyzing:
                analyzingView
            case .done:
                resultView
            case .error:
                errorView
            }

            Spacer(minLength: 16)

            statusBarView
        }
        #if os(macOS)
        .frame(minWidth: 560, minHeight: 600)
        #endif
        .background(
            Rectangle()
                .fill(.ultraThinMaterial)
                .ignoresSafeArea()
        )
        .onDrop(of: [.audio, .audiovisualContent, .mpeg4Movie, .mp3, .wav], isTargeted: $isDropTargeted) { providers in
            handleDrop(providers: providers)
        }
        .fileImporter(isPresented: $showFileImporter, allowedContentTypes: [.audio, .audiovisualContent, .mpeg4Movie, .mp3, .wav]) { result in
            switch result {
            case .success(let url):
                startAnalysis(url: url)
            case .failure(let error):
                errorMessage = error.localizedDescription
                analysisState = .error
            }
        }
    }

    // MARK: - Title Bar

    private var titleBar: some View {
        VStack(spacing: 8) {
            Text("🎵")
                .font(.system(size: 48))
            Text("Demo 独自升级")
                .font(.largeTitle.bold())
            Text("识谱引擎")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.top, 40)
        .padding(.bottom, 12)
    }

    #if os(iOS)
    // MARK: - iPad Server Connect Bar

    private var serverConnectBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "network")
                .foregroundStyle(.secondary)

            TextField("Mac 的 IP 地址 (如 192.168.1.5)", text: $serverHost)
                .textFieldStyle(.roundedBorder)
                .autocapitalization(.none)
                .disableAutocorrection(true)
                .frame(maxWidth: 220)

            Button(action: connectToServer) {
                if isConnecting {
                    ProgressView()
                        .scaleEffect(0.8)
                } else {
                    Text("连接")
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
            .disabled(isConnecting || serverHost.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
    }

    private func connectToServer() {
        let trimmed = serverHost.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }

        isConnecting = true
        ServerConfig.host = trimmed
        server.connect(to: trimmed)

        // 等待连接结果
        Task {
            // 给连接几秒时间
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            await MainActor.run { isConnecting = false }
        }
    }
    #endif

    // MARK: - Drop Zone

    private var dropZoneView: some View {
        VStack(spacing: 20) {
            ZStack {
                RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(
                        isDropTargeted ? Color.accentColor : Color.secondary.opacity(0.3),
                        style: StrokeStyle(lineWidth: isDropTargeted ? 3 : 2, dash: [8, 4])
                    )
                    .background(
                        RoundedRectangle(cornerRadius: 20)
                            .fill(isDropTargeted ? Color.accentColor.opacity(0.08) : Color.clear)
                    )

                VStack(spacing: 16) {
                    Image(systemName: "waveform.and.mic")
                        .font(.system(size: 48))
                        .foregroundStyle(isDropTargeted ? .blue : .secondary)

                    Text(isDropTargeted ? "松开以上传" : "拖拽音频/视频到此处")
                        .font(.title3)
                        .foregroundStyle(isDropTargeted ? .blue : .secondary)

                    Text("或")
                        .font(.caption)
                        .foregroundStyle(.secondary.opacity(0.5))

                    Button(action: { showFileImporter = true }) {
                        Label("选择文件...", systemImage: "doc.badge.plus")
                            .frame(width: 140)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Text("支持 MP3 / WAV / M4A / MP4 / MOV")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(40)
            }
            .frame(maxWidth: 480, minHeight: 260)
        }
        .padding(.horizontal, 40)
    }

    // MARK: - Analyzing

    private var analyzingView: some View {
        VStack(spacing: 24) {
            ProgressView()
                .scaleEffect(1.5)
                .padding(.bottom, 8)

            Text(analysisState == .uploading ? "正在上传音频..." : "正在分析音频...")
                .font(.headline)

            Text("视音频长度，可能需要 30-120 秒")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(60)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.ultraThinMaterial)
        )
    }

    // MARK: - Result

    private var resultView: some View {
        ScrollView {
            VStack(spacing: 16) {
                if let r = result {
                    infoCard(r)

                    if !r.chords.isEmpty {
                        chordCard(r)
                    }

                    jianpuCard(r)

                    if r.timbre.primary != "Unknown" {
                        timbreCard(r)
                    }
                }

                // 五线谱按钮
                if let r = result, r.musicxmlData != nil {
                    Button(action: { showSheetMusic = true }) {
                        Label("查看五线谱", systemImage: "music.note.list")
                            .frame(width: 160)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }

                Button(action: reset) {
                    Label("再分析一首", systemImage: "arrow.counterclockwise")
                        .frame(width: 160)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .padding(.top, 8)
                .padding(.bottom, 24)
            }
            .padding(.horizontal, 40)
            .sheet(isPresented: $showSheetMusic) {
                if let r = result, let xml = r.musicxmlData {
                    SheetMusicView(musicxmlData: xml, title: "\(r.keyDisplay) · \(r.bpmDisplay) · \(r.timeSig)")
                }
            }
        }
    }

    private func infoCard(_ r: AnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("基本信息", systemImage: "info.circle.fill")
                .font(.headline)

            LazyVGrid(columns: [
                GridItem(.flexible()),
                GridItem(.flexible())
            ], spacing: 12) {
                infoTag("调性", r.keyDisplay, .blue)
                infoTag("速度", r.bpmDisplay, .orange)
                infoTag("拍号", r.timeSig, .green)
                infoTag("乐器", r.timbre.primary, .purple)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(.ultraThinMaterial)
        )
    }

    private func infoTag(_ label: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 6) {
                Circle()
                    .fill(color)
                    .frame(width: 8, height: 8)
                Text(value)
                    .font(.system(.body, design: .rounded).weight(.medium))
            }
        }
    }

    private func chordCard(_ r: AnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("和弦分析", systemImage: "music.quarternote.3")
                .font(.headline)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Array(r.chords.enumerated()), id: \.offset) { i, chord in
                        HStack(spacing: 4) {
                            VStack(spacing: 2) {
                                Text(chord.symbol)
                                    .font(.system(.callout, design: .monospaced).weight(.bold))
                                Text(chord.function)
                                    .font(.caption2)
                                    .foregroundStyle(functionColor(chord.function))
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(.ultraThinMaterial)
                            )

                            if i < r.chords.count - 1 {
                                Image(systemName: "arrow.right")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            HStack(spacing: 8) {
                Text("功能：")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(r.chordProgression)
                    .font(.caption.weight(.medium))
            }

            if r.hasWarning {
                ForEach(r.warnings, id: \.self) { warning in
                    HStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.caption)
                            .foregroundStyle(.orange)
                        Text(warning)
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(.ultraThinMaterial)
        )
    }

    private func jianpuCard(_ r: AnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("首调简谱", systemImage: "text.justify")
                .font(.headline)

            Text(r.jianpu)
                .font(.system(.body, design: .monospaced))
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(.background.opacity(0.5))
                )
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(.ultraThinMaterial)
        )
    }

    private func timbreCard(_ r: AnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("音色分布", systemImage: "waveform")
                .font(.headline)

            HStack(spacing: 12) {
                ForEach(r.timbre.distribution.sorted(by: { $0.value > $1.value }), id: \.key) { instrument, count in
                    VStack(spacing: 4) {
                        Text(instrument)
                            .font(.caption.weight(.medium))
                        Text("\(count) 音符")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(.ultraThinMaterial)
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(.ultraThinMaterial)
        )
    }

    // MARK: - Error

    private var errorView: some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.orange)

            Text("分析失败")
                .font(.headline)

            if let msg = errorMessage {
                Text(msg)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            Button(action: reset) {
                Label("重试", systemImage: "arrow.counterclockwise")
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(60)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(.ultraThinMaterial)
        )
    }

    // MARK: - Status Bar

    private var statusBarView: some View {
        HStack {
            Circle()
                .fill(statusColor)
                .frame(width: 8, height: 8)

            Text(statusText)
                .font(.caption)
                .foregroundStyle(.secondary)

            Spacer()

            Text(ServerConfig.host == "localhost" ? "端口 8090" : "\(ServerConfig.host):8090")
                .font(.caption2)
                .foregroundStyle(.secondary.opacity(0.6))
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 10)
        .background(
            Rectangle()
                .fill(.ultraThickMaterial)
        )
    }

    private var statusColor: Color {
        switch server.status {
        case .running: .green
        case .starting: .yellow
        case .failed: .red
        case .stopped: .gray
        }
    }

    private var statusText: String {
        switch server.status {
        case .running:
            #if os(macOS)
            "服务器就绪"
            #else
            "已连接 Mac 服务器"
            #endif
        case .starting: "正在连接..."
        case .failed(let msg): msg
        case .stopped: "未连接"
        }
    }

    // MARK: - Actions

    private func handleDrop(providers: [NSItemProvider]) -> Bool {
        guard let provider = providers.first else { return false }

        let types: [UTType] = [.audio, .audiovisualContent, .mpeg4Movie, .mp3, .wav]
        for type in types {
            if provider.hasItemConformingToTypeIdentifier(type.identifier) {
                provider.loadItem(forTypeIdentifier: type.identifier, options: nil) { item, _ in
                    if let url = item as? URL {
                        DispatchQueue.main.async {
                            startAnalysis(url: url)
                        }
                    } else if let data = item as? Data {
                        let tmpDir = FileManager.default.temporaryDirectory
                        let tmpFile = tmpDir.appendingPathComponent("dropped-\(UUID().uuidString).wav")
                        try? data.write(to: tmpFile)
                        DispatchQueue.main.async {
                            startAnalysis(url: tmpFile)
                        }
                    }
                }
                return true
            }
        }
        return false
    }

    private func startAnalysis(url: URL) {
        guard case .running = server.status else {
            errorMessage = "服务器未就绪，请先连接引擎"
            analysisState = .error
            return
        }

        let isSecurityScoped = url.startAccessingSecurityScopedResource()

        withAnimation {
            analysisState = .uploading
            errorMessage = nil
            result = nil
        }

        Task {
            defer { if isSecurityScoped { url.stopAccessingSecurityScopedResource() } }
            do {
                withAnimation { analysisState = .analyzing }
                let r = try await APIClient.analyze(audioURL: url)
                await MainActor.run {
                    withAnimation {
                        result = r
                        analysisState = .done
                    }
                }
            } catch {
                await MainActor.run {
                    withAnimation {
                        errorMessage = error.localizedDescription
                        analysisState = .error
                    }
                }
            }
        }
    }

    private func reset() {
        withAnimation {
            analysisState = .idle
            result = nil
            errorMessage = nil
        }
    }

    private func functionColor(_ f: String) -> Color {
        switch f {
        case "T": return .green
        case "S": return .blue
        case "D": return .orange
        default: return .secondary
        }
    }
}
