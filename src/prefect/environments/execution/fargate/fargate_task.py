import os
import warnings
from typing import Any, Callable, List, TYPE_CHECKING

import prefect
from prefect import config
from prefect.environments.execution import Environment
from prefect.utilities.storage import get_flow_image

if TYPE_CHECKING:
    from prefect.core.flow import Flow  # pylint: disable=W0611


class FargateTaskEnvironment(Environment):
    """
    FargateTaskEnvironment is an environment which deploys your flow as a Fargate task.
    This environment requires AWS credentials and extra boto3 kwargs which
    are used in the creation and running of the Fargate task.

    When providing a custom container definition spec the first container in the spec must be the
    container that the flow runner will be executed on.

    The following environment variables, required for cloud, do not need to be
    included––they are automatically added and populated during execution:

    - `PREFECT__CLOUD__GRAPHQL`
    - `PREFECT__CLOUD__AUTH_TOKEN`
    - `PREFECT__CONTEXT__FLOW_RUN_ID`
    - `PREFECT__CONTEXT__IMAGE`
    - `PREFECT__CLOUD__USE_LOCAL_SECRETS`
    - `PREFECT__ENGINE__FLOW_RUNNER__DEFAULT_CLASS`
    - `PREFECT__ENGINE__TASK_RUNNER__DEFAULT_CLASS`
    - `PREFECT__LOGGING__LOG_TO_CLOUD`
    - `PREFECT__LOGGING__EXTRA_LOGGERS`

    Additionally, the following command will be applied to the first container:

    `$ /bin/sh -c "python -c 'import prefect; prefect.environments.FargateTaskEnvironment().run_flow()'"`

    All `kwargs` are accepted that one would normally pass to boto3 for `register_task_definition`
    and `run_task`. For information on the kwargs supported visit the following links:

    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.register_task_definition

    https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html#ECS.Client.run_task

    Note: You must provide `family` and `taskDefinition` with the same string so they match on run of the task.

    The secrets and kwargs that are provided at initialization time of this environment
    are not serialized and will only ever exist on this object.

    Args:
        - launch_type (str, optional): either FARGATE or EC2, defaults to FARGATE
        - aws_access_key_id (str, optional): AWS access key id for connecting the boto3
            client. Defaults to the value set in the environment variable
            `AWS_ACCESS_KEY_ID` or `None`
        - aws_access_key_id (str, optional): AWS access key id for connecting the boto3
            client. Defaults to the value set in the environment variable
            `AWS_ACCESS_KEY_ID` or `None`
        - aws_secret_access_key (str, optional): AWS secret access key for connecting
            the boto3 client. Defaults to the value set in the environment variable
            `AWS_SECRET_ACCESS_KEY` or `None`
        - aws_session_token (str, optional): AWS session key for connecting the boto3
            client. Defaults to the value set in the environment variable
            `AWS_SESSION_TOKEN` or `None`
        - region_name (str, optional): AWS region name for connecting the boto3 client.
            Defaults to the value set in the environment variable `REGION_NAME` or `None`
        - executor (Executor, optional): the executor to run the flow with. If not provided, the
            default executor will be used.
        - executor_kwargs (dict, optional): DEPRECATED
        - labels (List[str], optional): a list of labels, which are arbitrary string identifiers used by Prefect
            Agents when polling for work
        - on_start (Callable, optional): a function callback which will be called before the flow begins to run
        - on_exit (Callable, optional): a function callback which will be called after the flow finishes its run
        - metadata (dict, optional): extra metadata to be set and serialized on this environment
        - **kwargs (dict, optional): additional keyword arguments to pass to boto3 for
            `register_task_definition` and `run_task`
    """

    def __init__(  # type: ignore
        self,
        launch_type: str = "FARGATE",
        aws_access_key_id: str = None,
        aws_secret_access_key: str = None,
        aws_session_token: str = None,
        region_name: str = None,
        executor: "prefect.engine.executors.Executor" = None,
        executor_kwargs: dict = None,
        labels: List[str] = None,
        on_start: Callable = None,
        on_exit: Callable = None,
        metadata: dict = None,
        **kwargs,
    ) -> None:
        self.launch_type = launch_type
        # Not serialized, only stored on the object
        self.aws_access_key_id = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = aws_secret_access_key or os.getenv(
            "AWS_SECRET_ACCESS_KEY"
        )
        self.aws_session_token = aws_session_token or os.getenv("AWS_SESSION_TOKEN")
        self.region_name = region_name or os.getenv("REGION_NAME")

        # Parse accepted kwargs for definition and run
        self.task_definition_kwargs, self.task_run_kwargs = self._parse_kwargs(kwargs)

        if executor_kwargs is not None:
            warnings.warn("`executor_kwargs` is deprecated, use `executor` instead")
        if executor is None:
            executor = prefect.engine.get_default_executor_class()(
                **(executor_kwargs or {})
            )
        elif not isinstance(executor, prefect.engine.executors.Executor):
            raise TypeError(
                f"`executor` must be an `Executor` or `None`, got `{executor}`"
            )
        self.executor = executor

        super().__init__(
            labels=labels, on_start=on_start, on_exit=on_exit, metadata=metadata
        )

    def _parse_kwargs(self, user_kwargs: dict) -> tuple:
        """
        Parse the kwargs passed in and separate them out for `register_task_definition`
        and `run_task`. This is required because boto3 does not allow extra kwargs
        and if they are provided it will raise botocore.exceptions.ParamValidationError.

        Args:
            - user_kwargs (dict): The kwargs passed to the initialization of the environment

        Returns:
            tuple: a tuple of two dictionaries (task_definition_kwargs, task_run_kwargs)
        """
        definition_kwarg_list = [
            "family",
            "taskRoleArn",
            "executionRoleArn",
            "networkMode",
            "containerDefinitions",
            "volumes",
            "placementConstraints",
            "requiresCompatibilities",
            "cpu",
            "memory",
            "tags",
            "pidMode",
            "ipcMode",
            "proxyConfiguration",
            "inferenceAccelerators",
        ]

        run_kwarg_list = [
            "cluster",
            "taskDefinition",
            "count",
            "startedBy",
            "group",
            "placementConstraints",
            "placementStrategy",
            "platformVersion",
            "networkConfiguration",
            "tags",
            "enableECSManagedTags",
            "propagateTags",
        ]

        task_definition_kwargs = {}
        for key, item in user_kwargs.items():
            if key in definition_kwarg_list:
                task_definition_kwargs.update({key: item})

        task_run_kwargs = {}
        for key, item in user_kwargs.items():
            if key in run_kwarg_list:
                task_run_kwargs.update({key: item})

        return task_definition_kwargs, task_run_kwargs

    @property
    def dependencies(self) -> list:
        return ["boto3", "botocore"]

    def setup(self, flow: "Flow") -> None:  # type: ignore
        """
        Register the task definition if it does not already exist.

        Args:
            - flow (Flow): the Flow object
        """
        from boto3 import client as boto3_client
        from botocore.exceptions import ClientError

        boto3_c = boto3_client(
            "ecs",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token,
            region_name=self.region_name,
        )

        definition_exists = True
        try:
            boto3_c.describe_task_definition(
                taskDefinition=self.task_definition_kwargs.get("family")
            )
        except ClientError:
            definition_exists = False

        if not definition_exists:
            env_values = [
                {"name": "PREFECT__CLOUD__GRAPHQL", "value": config.cloud.graphql},
                {"name": "PREFECT__CLOUD__USE_LOCAL_SECRETS", "value": "false"},
                {
                    "name": "PREFECT__ENGINE__FLOW_RUNNER__DEFAULT_CLASS",
                    "value": "prefect.engine.cloud.CloudFlowRunner",
                },
                {
                    "name": "PREFECT__ENGINE__TASK_RUNNER__DEFAULT_CLASS",
                    "value": "prefect.engine.cloud.CloudTaskRunner",
                },
                {"name": "PREFECT__LOGGING__LOG_TO_CLOUD", "value": "true"},
                {
                    "name": "PREFECT__LOGGING__EXTRA_LOGGERS",
                    "value": str(config.logging.extra_loggers),
                },
            ]

            # create containerDefinitions if they do not exist
            if not self.task_definition_kwargs.get("containerDefinitions"):
                self.task_definition_kwargs["containerDefinitions"] = []
                self.task_definition_kwargs["containerDefinitions"].append({})

            # set environment variables for all containers
            for definition in self.task_definition_kwargs["containerDefinitions"]:
                if not definition.get("environment"):
                    definition["environment"] = []
                definition["environment"].extend(env_values)

            # set name on first container
            if not self.task_definition_kwargs["containerDefinitions"][0].get("name"):
                self.task_definition_kwargs["containerDefinitions"][0]["name"] = ""

            self.task_definition_kwargs.get("containerDefinitions")[0][
                "name"
            ] = "flow-container"

            # set image on first container
            if not self.task_definition_kwargs["containerDefinitions"][0].get("image"):
                self.task_definition_kwargs["containerDefinitions"][0]["image"] = ""

            self.task_definition_kwargs.get("containerDefinitions")[0][
                "image"
            ] = get_flow_image(flow)

            # set command on first container
            if not self.task_definition_kwargs["containerDefinitions"][0].get(
                "command"
            ):
                self.task_definition_kwargs["containerDefinitions"][0]["command"] = []

            self.task_definition_kwargs.get("containerDefinitions")[0]["command"] = [
                "/bin/sh",
                "-c",
                "python -c 'import prefect; prefect.environments.FargateTaskEnvironment().run_flow()'",
            ]

            boto3_c.register_task_definition(**self.task_definition_kwargs)

    def execute(  # type: ignore
        self, flow: "Flow", **kwargs: Any
    ) -> None:
        """
        Run the Fargate task that was defined for this flow.

        Args:
            - flow (Flow): the Flow object
            - **kwargs (Any): additional keyword arguments to pass to the runner
        """
        from boto3 import client as boto3_client

        flow_run_id = prefect.context.get("flow_run_id", "unknown")
        container_overrides = [
            {
                "name": "flow-container",
                "environment": [
                    {
                        "name": "PREFECT__CLOUD__AUTH_TOKEN",
                        "value": config.cloud.agent.auth_token
                        or config.cloud.auth_token,
                    },
                    {"name": "PREFECT__CONTEXT__FLOW_RUN_ID", "value": flow_run_id},
                    {"name": "PREFECT__CONTEXT__IMAGE", "value": get_flow_image(flow)},
                ],
            }
        ]

        boto3_c = boto3_client(
            "ecs",
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token,
            region_name=self.region_name,
        )

        boto3_c.run_task(
            overrides={"containerOverrides": container_overrides},
            launchType=self.launch_type,
            **self.task_run_kwargs,
        )
