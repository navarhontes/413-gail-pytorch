import os
import json
import pickle
import argparse
import wandb

import torch
import gymnasium as gym
import numpy as np

from models.nets import Expert
from models.gail import GAIL, WANDB_LOGGING
from utils.funcs import gather_expert_data, process_traj_data

TRAJECTORY_ENVS = ["Walker2d-v4", "HalfCheetah-v4", "Hopper-v4", "Humanoid-v4", "HumanoidStandup-v4"]
ENVS = ["CartPole-v1", "Pendulum-v0", "BipedalWalker-v3"] + TRAJECTORY_ENVS



def main(env_name):
    ckpt_path = "ckpts"
    if not os.path.isdir(ckpt_path):
        os.mkdir(ckpt_path)
    
    # TODO: can just try catch or create some dictionary of names
    if env_name not in ENVS:
        print("The environment name is wrong!")
        return

    expert_ckpt_path = "experts"
    expert_ckpt_path = os.path.join(expert_ckpt_path, env_name)

    with open(os.path.join(expert_ckpt_path, "model_config.json")) as f:
        expert_config = json.load(f)

    ckpt_path = os.path.join(ckpt_path, env_name)
    if not os.path.isdir(ckpt_path):
        os.mkdir(ckpt_path)

    with open("config.json") as f:
        config = json.load(f)[env_name]

    with open(os.path.join(ckpt_path, "model_config.json"), "w") as f:
        json.dump(config, f, indent=4)

    env = gym.make(env_name)
    env.reset()

    state_dim = len(env.observation_space.high)
    if env_name in ["CartPole-v1"]:
        discrete = True
        action_dim = env.action_space.n
    else:
        discrete = False
        action_dim = env.action_space.shape[0]

    if torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"

    if env_name in TRAJECTORY_ENVS:
        expert_data = np.load(os.path.join(expert_ckpt_path, "trajectories.npz"), allow_pickle=True)
        expert_data = process_traj_data(expert_data)
    else:
        expert = Expert(
            state_dim, action_dim, discrete, **expert_config
        ).to(device)
        expert.pi.load_state_dict(
            torch.load(
                os.path.join(expert_ckpt_path, "policy.ckpt"), map_location=device
            )
        )
        obs, acs, rews = gather_expert_data(env, expert, config["num_steps_per_iter"])
        expert_data = {"obs": obs, "acs": acs, "rews": rews}

    for i in range(3):

        if WANDB_LOGGING:
            wandb.init(
                # set the wandb project where this run will be logged
                project="gail-ensemble",
                # track hyperparameters and run metadata
                config={
                    **config,
                    "environment": env_name,
                    "num_bags": 1,
                    "model_num": i,
                    "hidden_size": 50,
                }
            )
        model = GAIL(state_dim, action_dim, discrete, config).to(device)
        results = model.train(env, expert_data, print_every=1)
        if WANDB_LOGGING:
            wandb.finish()

    env.close()

    with open(os.path.join(ckpt_path, "results.pkl"), "wb") as f:
        pickle.dump(results, f)

    if hasattr(model, "pi"):
        torch.save(
            model.pi.state_dict(), os.path.join(ckpt_path, "policy.ckpt")
        )
    if hasattr(model, "v"):
        torch.save(
            model.v.state_dict(), os.path.join(ckpt_path, "value.ckpt")
        )
    if hasattr(model, "d"):
        torch.save(
            model.d.state_dict(), os.path.join(ckpt_path, "discriminator.ckpt")
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env_name",
        type=str,
        default="CartPole-v1",
        help=f"Type the environment name to run. \
            The possible environments are \
                {ENVS}"
    )
    args = parser.parse_args()

    main(**vars(args))
