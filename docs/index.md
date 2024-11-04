![MLKit](images/mlkit.svg){ align=left }
The MLKit helps you build services with custom machine-learning capabilities.
For example, the ML APY Prediction Oracle is an [agent service](https://docs.autonolas.network/open-autonomy/get_started/what_is_an_agent_service/) that predicts the yield of liquidity pools using customizable machine learning techniques. Currently, the live demo makes predictions for [Uniswap](https://uniswap.org/) and [SpookySwap](https://spooky.fi).

The agents collect historical liquidity pool data by making [subgraph](https://thegraph.com) queries. They preprocess the data, run an optimizer, train a prediction algorithm on a split of the data using the hyperparameters found on the previous step, test on the left-out data, and then train on the full data to prepare the algorithm for forecasting. Then, the agents transit to an estimation stage where they periodically compute the predictions and update the model's weights based on the most recent data that they fetch. Note that the agents reach consensus on all the steps involving the collection, preprocessing, optimization, training, testing, training on the full data, and forecasting.

In the live demo, the predictions are currently sent via a POST message to an HTTP server, but other alternatives to extend the service are possible. For example, the service could be extended to secure the contents to a public blockchain through a contract call.

## Demo

In order to run a local demo of the ML APY Prediction Oracle service:

1. [Set up your system](https://docs.autonolas.network/open-autonomy/guides/set_up/) to work with the Open Autonomy framework. We recommend that you use these commands:

    ```bash
    mkdir your_workspace && cd your_workspace
    touch Pipfile && pipenv --python 3.10 && pipenv shell

    pipenv install open-autonomy[all]==0.18.2
    autonomy init --remote --ipfs --reset --author=your_name
    ```

2. Fetch the ML APY Prediction Oracle service.

	```bash
	autonomy fetch valory/apy_estimation:0.1.0:bafybeie6cnzfdgndph6ioux2ls5bncqmmsa2lh4xjaa2aqeu4xueemaaou --service
	```

3. Build the Docker image of the service agents

	```bash
	cd apy_estimation
	autonomy build-image
	```

4. Prepare the `keys.json` file containing the wallet address and the private key for each of the agents.

    ??? example "Generating an example `keys.json` file"

        <span style="color:red">**WARNING: Use this file for testing purposes only. Never use the keys or addresses provided in this example in a production environment or for personal use.**</span>

        ```bash
        cat > keys.json << EOF
        [
          {
            "address": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
            "private_key": "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"
          },
          {
            "address": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
            "private_key": "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba"
          },
          {
            "address": "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
            "private_key": "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e"
          },
          {
            "address": "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
            "private_key": "0x4bbbf85ce3377467afe5d46f804f221813b2bb87f24d81f60f1fcdbf7cbf4356"
          }
        ]
        EOF
        ```

5. Build the service deployment.

    ```bash
    autonomy deploy build keys.json --aev -ltm
    ```

6. Run the service.

	```bash
	cd abci_build
	autonomy deploy run
	```

	You can cancel the local execution at any time by pressing ++ctrl+c++.

## Build

1. Fork the [MLKit repository](https://github.com/valory-xyz/apy-oracle).
2. Make the necessary adjustments to tailor the service to your needs. This could include:
    * Adjust configuration parameters (e.g., in the `service.yaml` file).
    * Expand the service finite-state machine with your custom states.
    * Set an environment variable to change a value in the service:
        * SERVICE_APY_DEPOSIT_ENDPOINT: The endpoint to use for publishing the APY estimations
        * SERVICE_APY_N_OBSERVATIONS: The number of observations to use for the timeseries for the optimization. This number of observations will be fetched for each pool.
        * USE_ACN: whether the ACN network will be used to set the Tendermint network on startup.
        * TM_P2P_ENDPOINT_NODE_0/TM_P2P_ENDPOINT_NODE_1/TM_P2P_ENDPOINT_NODE_2/TM_P2P_ENDPOINT_NODE_3: the p2p endpoints of the Tendermint nodes
3. Run your service as detailed above.

!!! tip "Looking for help building your own?"

    Refer to the [Autonolas Discord community](https://discord.com/invite/z2PT65jKqQ), or consider ecosystem services like [Valory Propel](https://propel.valory.xyz) for the fastest way to get your first autonomous service in production.