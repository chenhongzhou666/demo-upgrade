// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "DemoUpgrade",
    platforms: [.macOS(.v14), .iOS(.v16)],
    products: [
        .executable(name: "DemoUpgrade", targets: ["DemoUpgrade"])
    ],
    targets: [
        .executableTarget(
            name: "DemoUpgrade",
            path: "Sources/DemoUpgrade"
        )
    ]
)
