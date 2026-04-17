// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TarkaSDK",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "TarkaSDK", targets: ["TarkaSDK"]),
    ],
    targets: [
        .target(
            name: "TarkaSDK",
            dependencies: [],
            path: "Sources/TarkaSDK"
        ),
        .testTarget(
            name: "TarkaSDKTests",
            dependencies: ["TarkaSDK"],
            path: "Tests/TarkaSDKTests"
        ),
    ]
)
