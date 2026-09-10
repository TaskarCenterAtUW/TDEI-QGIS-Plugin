# -*- coding: utf-8 -*-
"""Load TDEI OSW GeoJSON files into a QGIS layer group."""

import os
import shutil
import tempfile

from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .tdei_jobs import zip_geojson_paths

PARENT_GROUP_NAME = 'TDEI'


def cache_dir_for(dataset_id):
    """Writable folder for a downloaded OSW package."""
    safe = ''.join(
        char if char.isalnum() or char in '-_.' else '_'
        for char in str(dataset_id))
    path = os.path.join(
        QgsApplication.qgisSettingsDirPath(), 'tdei_osw_cache', safe)
    os.makedirs(path, exist_ok=True)
    return path


def dataset_group_name(dataset_id):
    return str(dataset_id)


def dataset_id_from_node(node):
    """Return the TDEI dataset id for a layer-tree node, if any."""
    if node is None:
        return None
    layer = node.layer() if hasattr(node, 'layer') else None
    if layer is not None:
        value = layer.customProperty('tdei_dataset_id')
        if value:
            return str(value)
    if hasattr(node, 'customProperty'):
        value = node.customProperty('tdei_dataset_id')
        if value:
            return str(value)
    parent = node.parent() if hasattr(node, 'parent') else None
    if parent is not None:
        return dataset_id_from_node(parent)
    return None


def find_parent_group():
    """Return the top-level TDEI group, if it exists."""
    return QgsProject.instance().layerTreeRoot().findGroup(PARENT_GROUP_NAME)


def ensure_parent_group():
    """Find or create the parent TDEI group."""
    parent = find_parent_group()
    if parent is not None:
        return parent
    parent = QgsProject.instance().layerTreeRoot().addGroup(PARENT_GROUP_NAME)
    parent.setExpanded(True)
    return parent


def find_dataset_group(dataset_id):
    """Return the layer-tree group for this dataset, if it exists."""
    parent = find_parent_group()
    if parent is not None:
        group = parent.findGroup(dataset_group_name(dataset_id))
        if group is not None:
            return group
    return QgsProject.instance().layerTreeRoot().findGroup(
        dataset_group_name(dataset_id))


def is_dataset_loaded(dataset_id):
    """True when a group named with the TDEI dataset id is already in the project."""
    return find_dataset_group(dataset_id) is not None


def load_geojsons_into_group(dataset_id, geojson_paths, iface=None):
    """Create a group named ``dataset_id`` and add each GeoJSON as a layer.

    :returns: list of loaded QgsVectorLayer
    :raises ValueError: if no valid GeoJSON layers could be created
    """
    project = QgsProject.instance()
    parent = ensure_parent_group()
    group = parent.addGroup(dataset_group_name(dataset_id))
    group.setExpanded(True)
    group.setCustomProperty('tdei_dataset_id', str(dataset_id))

    loaded = []
    try:
        for path in geojson_paths:
            layer_name = os.path.splitext(os.path.basename(path))[0]
            layer = QgsVectorLayer(path, layer_name, 'ogr')
            if not layer.isValid():
                continue
            layer.setCustomProperty('tdei_dataset_id', str(dataset_id))
            project.addMapLayer(layer, False)
            group.addLayer(layer)
            loaded.append(layer)
        if not loaded:
            raise ValueError('No valid GeoJSON layers were found in the package.')
    except Exception:
        for layer in loaded:
            project.removeMapLayer(layer.id())
        _remove_group(group)
        raise

    if iface is not None:
        _zoom_to_layers(iface, loaded)
    return loaded


def layers_in_dataset_group(dataset_id):
    """Vector layers under the TDEI group for this dataset."""
    group = find_dataset_group(dataset_id)
    if group is None:
        return []
    layers = []
    for child in group.findLayers():
        layer = child.layer()
        if layer is not None and layer.isValid():
            layers.append(layer)
    return layers


def layers_for_osw_upload(iface, dataset_id):
    """Selected GeoJSON layers in this dataset, or the whole group."""
    group_layers = layers_in_dataset_group(dataset_id)
    selected = []
    view = iface.layerTreeView() if iface is not None else None
    if view is not None:
        group_ids = {layer.id() for layer in group_layers}
        for layer in view.selectedLayers():
            if layer is not None and layer.id() in group_ids:
                selected.append(layer)
    if selected:
        return selected
    return group_layers


def prepare_osw_package_zip(iface, dataset_id):
    """Zip group GeoJSONs (or the current selection) for a file-upload job."""
    layers = layers_for_osw_upload(iface, dataset_id)
    if not layers:
        raise ValueError('No GeoJSON layers found in this dataset group.')
    dest_zip = os.path.join(cache_dir_for(dataset_id), 'osw_upload.zip')
    temp_dir = tempfile.mkdtemp(prefix='tdei_osw_export_')
    try:
        paths = []
        for layer in layers:
            path = _geojson_path_for_layer(layer, temp_dir)
            if path:
                paths.append(path)
        return zip_geojson_paths(paths, dest_zip)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _geojson_path_for_layer(layer, temp_dir):
    source = (layer.source() or '').split('|')[0]
    if (
            source.lower().endswith(('.geojson', '.json'))
            and os.path.isfile(source)
            and not layer.isModified()):
        return source
    filename = os.path.basename(source) if source else '{}.geojson'.format(
        layer.name())
    if not filename.lower().endswith(('.geojson', '.json')):
        filename = '{}.geojson'.format(layer.name())
    dest = os.path.join(temp_dir, filename)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(filename)
        dest = os.path.join(temp_dir, '{}-{}{}'.format(stem, layer.id(), ext))
    _export_layer_geojson(layer, dest)
    return dest


def _export_layer_geojson(layer, dest_path):
    result = QgsVectorFileWriter.writeAsVectorFormat(
        layer, dest_path, 'utf-8', layer.crs(), 'GeoJSON')
    error = result[0] if isinstance(result, tuple) else result
    if error != QgsVectorFileWriter.NoError:
        raise ValueError(
            'Could not export layer "{}".'.format(layer.name()))


def zoom_to_dataset(dataset_id, iface):
    group = find_dataset_group(dataset_id)
    if group is None or iface is None:
        return
    layers = []
    for child in group.findLayers():
        layer = child.layer()
        if layer is not None:
            layers.append(layer)
    if layers:
        _zoom_to_layers(iface, layers)


def _remove_group(group):
    parent = group.parent()
    if parent is not None:
        parent.removeChildNode(group)


def _zoom_to_layers(iface, layers):
    canvas = iface.mapCanvas()
    dest_crs = canvas.mapSettings().destinationCrs()
    extent = QgsRectangle()
    extent.setNull()
    project = QgsProject.instance()
    for layer in layers:
        if not layer.isValid():
            continue
        layer_extent = layer.extent()
        if layer_extent.isEmpty() or layer_extent.isNull():
            continue
        transform = QgsCoordinateTransform(layer.crs(), dest_crs, project)
        try:
            layer_extent = transform.transformBoundingBox(layer_extent)
        except Exception:
            pass
        if extent.isNull():
            extent = QgsRectangle(layer_extent)
        else:
            extent.combineExtentWith(layer_extent)
    if not extent.isNull() and not extent.isEmpty():
        extent.scale(1.1)
        canvas.setExtent(extent)
        canvas.refresh()
