// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MarcutApp",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "MarcutApp", targets: ["MarcutApp"])
    ],
    dependencies: [
        .package(url: "https://github.com/pvieito/PythonKit.git", from: "0.5.1")
    ],
    targets: [
        .executableTarget(
            name: "MarcutApp",
            dependencies: [
                .product(name: "PythonKit", package: "PythonKit"),
            ],
            path: "Sources/MarcutApp",
            resources: [
                .process("Assets.xcassets"),
                .copy("Frameworks"),
                .copy("python_site"),
                .copy("Resources")
            ]
        ),
        .testTarget(
            name: "MarcutAppTests",
            dependencies: ["MarcutApp"],
            path: "Tests/MarcutAppTests"
        )
    ]
)
