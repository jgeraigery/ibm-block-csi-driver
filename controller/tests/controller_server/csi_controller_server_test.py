import unittest
# from unittest import mock as umock
import grpc

from mock import patch, Mock, call
from controller.tests import utils

from controller.csi_general import csi_pb2
from controller.array_action.array_mediator_xiv import XIVArrayMediator
from controller.controller_server.csi_controller_server import ControllerServicer
from controller.controller_server.test_settings import vol_name
import controller.array_action.errors as array_errors
import controller.controller_server.errors as controller_errors

from controller.controller_server.config import PARAMETERS_PREFIX

class TestControllerServerPublishVolume(unittest.TestCase):

    @patch("controller.array_action.array_mediator_xiv.XIVArrayMediator._connect")
    def setUp(self, connect):
        self.fqdn = "fqdn"
        self.hostname = "hostname"
        self.mediator = XIVArrayMediator("user", "password", self.fqdn)
        self.mediator.client = Mock()

        self.mediator.get_host_by_host_identifiers = Mock()
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["iscsi"]

        self.mediator.get_volume_mappings = Mock()
        self.mediator.get_volume_mappings.return_value = {}

        self.mediator.map_volume = Mock()
        self.mediator.map_volume.return_value = 1

        self.mediator.get_array_iqns = Mock()
        self.mediator.get_array_iqns.return_value = "array-iqn"

        self.servicer = ControllerServicer(self.fqdn)

        self.request = Mock()
        arr_type = XIVArrayMediator.array_type
        self.request.volume_id = "{}:wwn1".format(arr_type)
        self.request.node_id = "hostname;iqn.1994-05.com.redhat:686358c930fe;500143802426baf4"
        self.request.readonly = False
        self.request.readonly = False
        self.request.secrets = {"username": "user", "password": "pass", "management_address": "mg"}
        self.request.volume_context = {}

        caps = Mock()
        caps.mount = Mock()
        caps.mount.fs_type = "ext4"
        access_types = csi_pb2.VolumeCapability.AccessMode
        caps.access_mode.mode = access_types.SINGLE_NODE_WRITER
        self.request.volume_capability = caps

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_success(self, enter):
        enter.return_value = self.mediator

        context = utils.FakeContext()
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

    @patch("controller.controller_server.utils.validate_publish_volume_request")
    def test_publish_volume_validateion_exception(self, publish_validation):
        publish_validation.side_effect = [controller_errors.ValidationException("msg")]
        context = utils.FakeContext()
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.INVALID_ARGUMENT)
        self.assertTrue("msg" in context.details)

    def test_publish_volume_wrong_volume_id(self):
        self.request.volume_id = "some-wrong-id-format"

        context = utils.FakeContext()
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

    def test_publish_volume_wrong_node_id(self):
        self.request.node_id = "some-wrong-id-format"

        context = utils.FakeContext()
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_get_host_by_host_identifiers_exception(self, enter):
        context = utils.FakeContext()

        self.mediator.get_host_by_host_identifiers = Mock()
        self.mediator.get_host_by_host_identifiers.side_effect = [array_errors.MultipleHostsFoundError("", "")]
        enter.return_value = self.mediator

        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertTrue("Multiple hosts" in context.details)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)

        self.mediator.get_host_by_host_identifiers.side_effect = [array_errors.HostNotFoundError("")]
        enter.return_value = self.mediator

        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_get_volume_mappings_one_map_for_existing_host(self, enter):
        context = utils.FakeContext()
        self.mediator.get_volume_mappings = Mock()
        self.mediator.get_volume_mappings.return_value = {self.hostname: 2}
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '2')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"], "iscsi")

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_with_connectivity_type_fc(self, enter):
        context = utils.FakeContext()
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["iscsi", "fc"]
        self.mediator.get_array_fc_wwns = Mock()
        self.mediator.get_array_fc_wwns.return_value = ["500143802426baf4"]
        self.mediator.get_array_iqns = Mock()
        self.mediator.get_array_iqns.return_value = [
            "iqn.1994-05.com.redhat:686358c930fe"]
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '1')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"], "fc")
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_ARRAY_FC_INITIATORS"], "500143802426baf4")

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_with_connectivity_type_iscsi(self, enter):
        context = utils.FakeContext()
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["iscsi"]
        self.mediator.get_array_iqns = Mock()
        self.mediator.get_array_iqns.return_value = ["iqn.1994-05.com.redhat:686358c930fe"]
        self.mediator.get_array_fc_wwns = Mock()
        self.mediator.get_array_fc_wwns.return_value = ["500143802426baf4"]
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '1')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"],
                         "iscsi")
        self.assertEqual(
            res.publish_context["PUBLISH_CONTEXT_ARRAY_IQN"],
            "iqn.1994-05.com.redhat:686358c930fe")

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_with_node_id_only_has_iqns(self, enter):
        context = utils.FakeContext()
        self.request.node_id = "hostname;iqn.1994-05.com.redhat:686358c930fe;"
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["iscsi"]
        self.mediator.get_array_iqns = Mock()
        self.mediator.get_array_iqns.return_value = [
            "iqn.1994-05.com.redhat:686358c930fe"]
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '1')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"],
                         "iscsi")
        self.assertEqual(
            res.publish_context["PUBLISH_CONTEXT_ARRAY_IQN"],
            "iqn.1994-05.com.redhat:686358c930fe")

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_with_node_id_only_has_wwns(self, enter):
        context = utils.FakeContext()
        self.request.node_id = "hostname;;500143802426baf4"
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["fc"]
        self.mediator.get_array_fc_wwns = Mock()
        self.mediator.get_array_fc_wwns.return_value = ["500143802426baf4"]
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '1')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"],
                         "fc")
        self.assertEqual(
            res.publish_context["PUBLISH_CONTEXT_ARRAY_FC_INITIATORS"],
            "500143802426baf4")

        self.request.node_id = "hostname;;500143802426baf4:500143806626bae2"
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["fc"]
        self.mediator.get_array_fc_wwns = Mock()
        self.mediator.get_array_fc_wwns.return_value = ["500143802426baf4",
                                                        "500143806626bae2"]
        enter.return_value = self.mediator

        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '1')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"],
                         "fc")
        self.assertEqual(
            res.publish_context["PUBLISH_CONTEXT_ARRAY_FC_INITIATORS"],
            "500143802426baf4,500143806626bae2")

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_get_volume_mappings_one_map_for_other_host(self, enter):
        context = utils.FakeContext()
        self.mediator.get_volume_mappings = Mock()
        self.mediator.get_volume_mappings.return_value = {"other-hostname": 3}
        enter.return_value = self.mediator

        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.FAILED_PRECONDITION)
        self.assertTrue("Volume is already mapped" in context.details)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_get_volume_mappings_more_then_one_mapping(self, enter):
        context = utils.FakeContext()
        self.mediator.get_volume_mappings = Mock()
        self.mediator.get_volume_mappings.return_value = {"other-hostname": 3, self.hostname: 4}
        enter.return_value = self.mediator

        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.FAILED_PRECONDITION)
        self.assertTrue("Volume is already mapped" in context.details)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_map_volume_excpetions(self, enter):
        context = utils.FakeContext()

        self.mediator.map_volume.side_effect = [array_errors.PermissionDeniedError("msg")]

        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.PERMISSION_DENIED)

        self.mediator.map_volume.side_effect = [array_errors.VolumeNotFoundError("vol")]
        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

        self.mediator.map_volume.side_effect = [array_errors.HostNotFoundError("host")]
        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

        self.mediator.map_volume.side_effect = [array_errors.MappingError("", "", "")]
        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)

    @patch.object(XIVArrayMediator, "MAX_LUN_NUMBER", 3)
    @patch.object(XIVArrayMediator, "MIN_LUN_NUMBER", 1)
    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_publish_volume_map_volume_lun_already_in_use(self, enter):
        context = utils.FakeContext()

        self.mediator.map_volume.side_effect = [array_errors.LunAlreadyInUseError("", ""), 2]
        self.mediator.map_volume.get_array_iqns.return_value = "array-iqn"
        enter.return_value = self.mediator
        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '2')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"], "iscsi")

        self.mediator.map_volume.side_effect = [
            array_errors.LunAlreadyInUseError("", ""), 2]
        self.mediator.get_host_by_host_identifiers = Mock()
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["fc"]
        self.mediator.get_array_fc_wwns = Mock()
        self.mediator.get_array_fc_wwns.return_value = ["500143802426baf4"]
        enter.return_value = self.mediator
        res = self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '2')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"],
                         "fc")

        self.mediator.map_volume.side_effect = [array_errors.LunAlreadyInUseError("", ""),
                                                array_errors.LunAlreadyInUseError("", ""), 2]
        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_LUN"], '2')
        self.assertEqual(res.publish_context["PUBLISH_CONTEXT_CONNECTIVITY"], "fc")

        self.mediator.map_volume.side_effect = [
                                                   array_errors.LunAlreadyInUseError("", "")] * (
                                                           self.mediator.max_lun_retries + 1)
        enter.return_value = self.mediator
        self.servicer.ControllerPublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.RESOURCE_EXHAUSTED)


class TestControllerServerUnPublishVolume(unittest.TestCase):

    @patch("controller.array_action.array_mediator_xiv.XIVArrayMediator._connect")
    def setUp(self, connect):
        self.fqdn = "fqdn"
        self.hostname = "hostname"
        self.mediator = XIVArrayMediator("user", "password", self.fqdn)
        self.mediator.client = Mock()

        self.mediator.get_host_by_host_identifiers = Mock()
        self.mediator.get_host_by_host_identifiers.return_value = self.hostname, ["iscsi"]

        self.mediator.unmap_volume = Mock()
        self.mediator.unmap_volume.return_value = None

        self.servicer = ControllerServicer(self.fqdn)

        self.request = Mock()
        arr_type = XIVArrayMediator.array_type
        self.request.volume_id = "{}:wwn1".format(arr_type)
        self.request.node_id = "hostname;iqn1;500143802426baf4"
        self.request.secrets = {"username": "user", "password": "pass", "management_address": "mg"}
        self.request.volume_context = {}

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_unpublish_volume_success(self, enter):
        enter.return_value = self.mediator
        context = utils.FakeContext()
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)

    @patch("controller.controller_server.utils.validate_unpublish_volume_request")
    def test_unpublish_volume_validation_exception(self, publish_validation):
        publish_validation.side_effect = [controller_errors.ValidationException("msg")]
        context = utils.FakeContext()
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.INVALID_ARGUMENT)
        self.assertTrue("msg" in context.details)

    def test_unpublish_volume_wrong_volume_id(self):
        self.request.volume_id = "some-wrong-id-format"

        context = utils.FakeContext()
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.INVALID_ARGUMENT)

    def test_unpublish_volume_wrong_node_id(self):
        self.request.node_id = "some-wrong-id-format"

        context = utils.FakeContext()
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_unpublish_volume_get_host_by_host_identifiers_exception(self, enter):
        context = utils.FakeContext()

        self.mediator.get_host_by_host_identifiers = Mock()
        self.mediator.get_host_by_host_identifiers.side_effect = [array_errors.MultipleHostsFoundError("", "")]
        enter.return_value = self.mediator

        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertTrue("Multiple hosts" in context.details)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)

        self.mediator.get_host_by_host_identifiers.side_effect = [array_errors.HostNotFoundError("")]
        enter.return_value = self.mediator

        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

    @patch("controller.array_action.array_connection_manager.ArrayConnectionManager.__enter__")
    def test_unpublish_volume_unmap_volume_excpetions(self, enter):
        context = utils.FakeContext()

        self.mediator.unmap_volume.side_effect = [array_errors.PermissionDeniedError("msg")]
        enter.return_value = self.mediator
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.PERMISSION_DENIED)

        context = utils.FakeContext()
        self.mediator.unmap_volume.side_effect = [array_errors.VolumeNotFoundError("vol")]
        enter.return_value = self.mediator
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

        context = utils.FakeContext()
        self.mediator.unmap_volume.side_effect = [array_errors.HostNotFoundError("host")]
        enter.return_value = self.mediator
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.NOT_FOUND)

        context = utils.FakeContext()
        self.mediator.unmap_volume.side_effect = [array_errors.UnMappingError("", "", "")]
        enter.return_value = self.mediator
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)

        context = utils.FakeContext()
        self.mediator.unmap_volume.side_effect = [array_errors.VolumeAlreadyUnmappedError("")]
        enter.return_value = self.mediator
        self.servicer.ControllerUnpublishVolume(self.request, context)
        self.assertEqual(context.code, grpc.StatusCode.OK)


class TestControllerServerGetCapabilities(unittest.TestCase):

    def setUp(self):
        self.fqdn = "fqdn"
        self.servicer = ControllerServicer(self.fqdn)

    def test_controller_get_capabilities(self):
        request = Mock()
        context = Mock()
        self.servicer.ControllerGetCapabilities(request, context)


class TestIdentityServer(unittest.TestCase):

    def setUp(self):
        self.fqdn = "fqdn"
        self.servicer = ControllerServicer(self.fqdn)

    @patch.object(ControllerServicer, "_ControllerServicer__get_identity_config")
    def test_identity_plugin_get_info_succeeds(self, identity_config):
        plugin_name = "plugin-name"
        version = "1.1.0"
        identity_config.side_effect = [plugin_name, version]
        request = Mock()
        context = Mock()
        request.volume_capabilities = []
        res = self.servicer.GetPluginInfo(request, context)
        self.assertEqual(res, csi_pb2.GetPluginInfoResponse(name=plugin_name, vendor_version=version))

    @patch.object(ControllerServicer, "_ControllerServicer__get_identity_config")
    def test_identity_plugin_get_info_fails_when_attributes_from_config_are_missing(self, identity_config):
        request = Mock()
        context = Mock()

        identity_config.side_effect = ["name", Exception(), Exception(), "1.1.0"]

        res = self.servicer.GetPluginInfo(request, context)
        context.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
        self.assertEqual(res, csi_pb2.GetPluginInfoResponse())

        res = self.servicer.GetPluginInfo(request, context)
        self.assertEqual(res, csi_pb2.GetPluginInfoResponse())
        context.set_code.assert_called_with(grpc.StatusCode.INTERNAL)

    @patch.object(ControllerServicer, "_ControllerServicer__get_identity_config")
    def test_identity_plugin_get_info_fails_when_name_or_value_are_empty(self, identity_config):
        request = Mock()
        context = Mock()

        identity_config.side_effect = ["", "1.1.0", "name", ""]

        res = self.servicer.GetPluginInfo(request, context)
        context.set_code.assert_called_once_with(grpc.StatusCode.INTERNAL)
        self.assertEqual(res, csi_pb2.GetPluginInfoResponse())

        res = self.servicer.GetPluginInfo(request, context)
        self.assertEqual(res, csi_pb2.GetPluginInfoResponse())
        self.assertEqual(context.set_code.call_args_list,
                         [call(grpc.StatusCode.INTERNAL), call(grpc.StatusCode.INTERNAL)])

    def test_identity_get_plugin_capabilities(self):
        request = Mock()
        context = Mock()
        self.servicer.GetPluginCapabilities(request, context)

    def test_identity_probe(self):
        request = Mock()
        context = Mock()
        self.servicer.Probe(request, context)
