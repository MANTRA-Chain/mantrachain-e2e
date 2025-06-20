import "hardhat-typechain";

module.exports = {
  solidity: {
    compilers: [
      {
        version: "0.8.24",
        settings: {
          "viaIR": true,
          "optimizer": {
            "enabled": true,
            "runs": 100000
          },
          "evmVersion": "cancun",
          "metadata": {
            "bytecodeHash": "none",
            "appendCBOR": false
          }
        }
      },
    ],
  },
  typechain: {
    outDir: "typechain",
    target: "ethers-v5",
    runOnCompile: true
  }
};
