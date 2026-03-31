// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TarkaSDK",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "FraudStackSDK", targets: ["FraudStackSDK"])
    ],
    targets: [
        .target(name: "FraudStackSDK", path: "Sources/FraudStackSDK")
    ]
)
