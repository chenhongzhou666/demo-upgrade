import SwiftUI
import WebKit

struct SheetMusicView: View {
    let musicxmlData: String
    let title: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                Button("关闭") { dismiss() }
                    .buttonStyle(.plain)
            }
            .padding(.horizontal)
            .padding(.top, 12)
            .padding(.bottom, 8)

            Divider()

            SheetMusicWebView(musicxmlData: musicxmlData)
        }
        #if os(iOS)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        #endif
    }
}

#if os(macOS)
struct SheetMusicWebView: NSViewRepresentable {
    let musicxmlData: String

    func makeNSView(context: Context) -> WKWebView {
        let wv = WKWebView()
        wv.setValue(false, forKey: "drawsBackground")
        wv.loadHTMLString(buildHTML(musicxmlData), baseURL: nil)
        return wv
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}
}
#else
struct SheetMusicWebView: UIViewRepresentable {
    let musicxmlData: String

    func makeUIView(context: Context) -> WKWebView {
        let wv = WKWebView()
        wv.isOpaque = false
        wv.backgroundColor = .clear
        wv.loadHTMLString(buildHTML(musicxmlData), baseURL: nil)
        return wv
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
#endif

private func buildHTML(_ xmlData: String) -> String {
    guard let data = Data(base64Encoded: xmlData),
          let xml = String(data: data, encoding: .utf8) else {
        return "<html><body><p style='color:gray;padding:40px;text-align:center;font-family:-apple-system;'>无法解析乐谱数据</p></body></html>"
    }

    let escapedXML = xml
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "`", with: "\\`")
        .replacingOccurrences(of: "$", with: "\\$")
        .replacingOccurrences(of: "\n", with: "\\n")
        .replacingOccurrences(of: "\r", with: "")

    return """
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=3.0, user-scalable=yes">
    <script src="https://cdn.jsdelivr.net/npm/opensheetmusicdisplay@1.8.2/build/opensheetmusicdisplay.min.js"></script>
    <style>
    * { margin: 0; padding: 0; }
    body { background: transparent; padding: 16px; }
    #osmd-container { width: 100%; }
    </style>
    </head>
    <body>
    <div id="osmd-container"></div>
    <script>
    (async function() {
        try {
            const xml = `\(escapedXML)`;
            const container = document.getElementById('osmd-container');
            const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
                autoResize: true,
                backend: 'svg',
                drawTitle: true,
                drawSubtitle: false,
                drawComposer: false,
            });
            await osmd.load(xml);
            osmd.render();
            const svg = container.querySelector('svg');
            if (svg) {
                svg.style.width = '100%';
                svg.style.height = 'auto';
            }
        } catch(e) {
            document.body.innerHTML = '<p style="color:red;padding:20px;font-family:-apple-system;">五线谱渲染失败: ' + e.message + '</p>';
        }
    })();
    </script>
    </body>
    </html>
    """
}
