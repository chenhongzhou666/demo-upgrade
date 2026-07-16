import SwiftUI

#if os(macOS)
import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    var server: ServerManager?

    func applicationWillTerminate(_ notification: Notification) {
        server?.stop()
    }
}
#endif

@main
struct DemoUpgradeApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    #endif

    @StateObject private var server = ServerManager()

    var body: some Scene {
        WindowGroup {
            ZStack {
                #if os(macOS)
                // macOS: 先启动本地服务器
                switch server.status {
                case .starting:
                    splashView(title: "正在启动识谱引擎…",
                              subtitle: "首次启动可能需要下载模型文件")
                        .frame(width: 400, height: 300)

                case .failed(let msg):
                    VStack(spacing: 16) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.largeTitle)
                            .foregroundStyle(.orange)
                        Text("引擎启动失败")
                            .font(.headline)
                        Text(msg)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 40)
                        Button("重试") { server.start() }
                            .buttonStyle(.borderedProminent)
                    }
                    .frame(width: 400, height: 300)

                case .stopped, .running:
                    ContentView()
                        .environmentObject(server)
                }
                #else
                // iOS/iPadOS: 直接显示，用户手动输入 Mac IP 连接
                ContentView()
                    .environmentObject(server)
                #endif
            }
            #if os(macOS)
            .frame(minWidth: 560, minHeight: 600)
            #endif
            .task {
                #if os(macOS)
                appDelegate.server = server
                server.start()
                #endif
            }
        }
        #if os(macOS)
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
        .defaultSize(width: 600, height: 700)
        #endif
    }

    private func splashView(title: String, subtitle: String) -> some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.2)
            Text(title)
                .font(.headline)
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
