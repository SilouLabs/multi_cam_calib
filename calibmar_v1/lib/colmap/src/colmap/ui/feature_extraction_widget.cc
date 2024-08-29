// Copyright (c) 2023, ETH Zurich and UNC Chapel Hill.
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
//     * Redistributions of source code must retain the above copyright
//       notice, this list of conditions and the following disclaimer.
//
//     * Redistributions in binary form must reproduce the above copyright
//       notice, this list of conditions and the following disclaimer in the
//       documentation and/or other materials provided with the distribution.
//
//     * Neither the name of ETH Zurich and UNC Chapel Hill nor the names of
//       its contributors may be used to endorse or promote products derived
//       from this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDERS OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.

#include "colmap/ui/feature_extraction_widget.h"

#include "colmap/controllers/feature_extraction.h"
#include "colmap/sensor/models.h"
#include "colmap/sensor/models_refrac.h"
#include "colmap/ui/options_widget.h"
#include "colmap/ui/qt_utils.h"
#include "colmap/ui/thread_control_widget.h"

namespace colmap {

class ExtractionWidget : public OptionsWidget {
 public:
  ExtractionWidget(QWidget* parent, OptionManager* options);

  virtual void Run() = 0;

 protected:
  OptionManager* options_;
  ThreadControlWidget* thread_control_widget_;
};

class SIFTExtractionWidget : public ExtractionWidget {
 public:
  SIFTExtractionWidget(QWidget* parent, OptionManager* options);

  void Run() override;
};

class ImportFeaturesWidget : public ExtractionWidget {
 public:
  ImportFeaturesWidget(QWidget* parent, OptionManager* options);

  void Run() override;

 private:
  std::string import_path_;
};

ExtractionWidget::ExtractionWidget(QWidget* parent, OptionManager* options)
    : OptionsWidget(parent),
      options_(options),
      thread_control_widget_(new ThreadControlWidget(this)) {}

SIFTExtractionWidget::SIFTExtractionWidget(QWidget* parent,
                                           OptionManager* options)
    : ExtractionWidget(parent, options) {
  AddOptionDirPath(&options->image_reader->mask_path, "mask_path");
  AddOptionFilePath(&options->image_reader->camera_mask_path,
                    "camera_mask_path");
  // Directory that contains Pose prior files (.csv).
  AddOptionDirPath(&options->image_reader->pose_prior_path, "pose_prior_path");

  AddOptionInt(&options->sift_extraction->max_image_size, "max_image_size");
  AddOptionInt(&options->sift_extraction->max_num_features, "max_num_features");
  AddOptionInt(&options->sift_extraction->first_octave, "first_octave", -5);
  AddOptionInt(&options->sift_extraction->num_octaves, "num_octaves");
  AddOptionInt(&options->sift_extraction->octave_resolution,
               "octave_resolution");
  AddOptionDouble(&options->sift_extraction->peak_threshold,
                  "peak_threshold",
                  0.0,
                  1e7,
                  0.00001,
                  5);
  AddOptionDouble(&options->sift_extraction->edge_threshold, "edge_threshold");
  AddOptionBool(&options->sift_extraction->estimate_affine_shape,
                "estimate_affine_shape");
  AddOptionInt(&options->sift_extraction->max_num_orientations,
               "max_num_orientations");
  AddOptionBool(&options->sift_extraction->upright, "upright");
  AddOptionBool(&options->sift_extraction->domain_size_pooling,
                "domain_size_pooling");
  AddOptionDouble(&options->sift_extraction->dsp_min_scale,
                  "dsp_min_scale",
                  0.0,
                  1e7,
                  0.00001,
                  5);
  AddOptionDouble(&options->sift_extraction->dsp_max_scale,
                  "dsp_max_scale",
                  0.0,
                  1e7,
                  0.00001,
                  5);
  AddOptionInt(&options->sift_extraction->dsp_num_scales, "dsp_num_scales", 1);

  AddOptionInt(&options->sift_extraction->num_threads, "num_threads", -1);
  AddOptionBool(&options->sift_extraction->use_gpu, "use_gpu");
  AddOptionText(&options->sift_extraction->gpu_index, "gpu_index");
}

void SIFTExtractionWidget::Run() {
  WriteOptions();

  ImageReaderOptions reader_options = *options_->image_reader;
  reader_options.database_path = *options_->database_path;
  reader_options.image_path = *options_->image_path;

  auto extractor = CreateFeatureExtractorController(reader_options,
                                                    *options_->sift_extraction);
  thread_control_widget_->StartThread(
      "Extracting...", true, std::move(extractor));
}

ImportFeaturesWidget::ImportFeaturesWidget(QWidget* parent,
                                           OptionManager* options)
    : ExtractionWidget(parent, options) {
  AddOptionDirPath(&import_path_, "import_path");
}

void ImportFeaturesWidget::Run() {
  WriteOptions();

  if (!ExistsDir(import_path_)) {
    QMessageBox::critical(this, "", tr("Path is not a directory"));
    return;
  }

  ImageReaderOptions reader_options = *options_->image_reader;
  reader_options.database_path = *options_->database_path;
  reader_options.image_path = *options_->image_path;

  auto importer = CreateFeatureImporterController(reader_options, import_path_);
  thread_control_widget_->StartThread(
      "Importing...", true, std::move(importer));
}

FeatureExtractionWidget::FeatureExtractionWidget(QWidget* parent,
                                                 OptionManager* options)
    : parent_(parent), options_(options) {
  // Do not change flag, to make sure feature database is not accessed from
  // multiple threads
  setWindowFlags(Qt::Window);
  setWindowTitle("Feature extraction");

  QGridLayout* grid = new QGridLayout(this);

  grid->addWidget(CreateCameraModelBox(), 0, 0);
  grid->addWidget(CreateCameraRefracModelBox(), 1, 0);

  tab_widget_ = new QTabWidget(this);

  QScrollArea* extraction_widget = new QScrollArea(this);
  extraction_widget->setAlignment(Qt::AlignHCenter);
  extraction_widget->setWidget(new SIFTExtractionWidget(this, options));
  tab_widget_->addTab(extraction_widget, tr("Extract"));

  QScrollArea* import_widget = new QScrollArea(this);
  import_widget->setAlignment(Qt::AlignHCenter);
  import_widget->setWidget(new ImportFeaturesWidget(this, options));
  tab_widget_->addTab(import_widget, tr("Import"));

  grid->addWidget(tab_widget_);

  QPushButton* extract_button = new QPushButton(tr("Extract"), this);
  connect(extract_button,
          &QPushButton::released,
          this,
          &FeatureExtractionWidget::Extract);
  grid->addWidget(extract_button, grid->rowCount(), 0);
}

QGroupBox* FeatureExtractionWidget::CreateCameraModelBox() {
  camera_model_ids_.clear();

  camera_model_cb_ = new QComboBox(this);

#define CAMERA_MODEL_CASE(CameraModel)                                     \
  camera_model_cb_->addItem(                                               \
      QString::fromStdString(CameraModelIdToName(CameraModel::model_id))); \
  camera_model_ids_.push_back(static_cast<int>(CameraModel::model_id));

  CAMERA_MODEL_CASES

#undef CAMERA_MODEL_CASE

  camera_params_exif_rb_ = new QRadioButton(tr("Parameters from EXIF"), this);
  camera_params_exif_rb_->setChecked(true);

  camera_params_custom_rb_ = new QRadioButton(tr("Custom parameters"), this);

  camera_params_info_ = new QLabel(tr(""), this);
  QPalette pal = QPalette(camera_params_info_->palette());
  pal.setColor(QPalette::WindowText, QColor(130, 130, 130));
  camera_params_info_->setPalette(pal);

  camera_params_text_ = new QLineEdit(this);
  camera_params_text_->setEnabled(false);

  single_camera_cb_ = new QCheckBox("Shared for all images", this);
  single_camera_cb_->setChecked(false);

  single_camera_per_folder_cb_ = new QCheckBox("Shared per sub-folder", this);
  single_camera_per_folder_cb_->setChecked(false);

  QGroupBox* box = new QGroupBox(tr("Camera model"), this);

  QVBoxLayout* vbox = new QVBoxLayout(box);
  vbox->addWidget(camera_model_cb_);
  vbox->addWidget(camera_params_info_);
  vbox->addWidget(single_camera_cb_);
  vbox->addWidget(single_camera_per_folder_cb_);
  vbox->addWidget(camera_params_exif_rb_);
  vbox->addWidget(camera_params_custom_rb_);
  vbox->addWidget(camera_params_text_);
  vbox->addStretch(1);

  box->setLayout(vbox);

  SelectCameraModel(camera_model_cb_->currentIndex());

  connect(camera_model_cb_,
          (void(QComboBox::*)(int)) & QComboBox::currentIndexChanged,
          this,
          &FeatureExtractionWidget::SelectCameraModel);
  connect(camera_params_exif_rb_,
          &QRadioButton::clicked,
          camera_params_text_,
          &QLineEdit::setDisabled);
  connect(camera_params_custom_rb_,
          &QRadioButton::clicked,
          camera_params_text_,
          &QLineEdit::setEnabled);

  return box;
}

QGroupBox* FeatureExtractionWidget::CreateCameraRefracModelBox() {
  camera_refrac_model_ids_.clear();

  camera_refrac_model_cb_ = new QComboBox(this);

  camera_refrac_model_cb_->addItem(QString::fromStdString("NONE"));
  camera_refrac_model_ids_.push_back(
      static_cast<int>(CameraRefracModelId::kInvalid));
#define CAMERA_REFRAC_MODEL_CASE(CameraRefracModel)                    \
  camera_refrac_model_cb_->addItem(QString::fromStdString(             \
      CameraRefracModelIdToName(CameraRefracModel::refrac_model_id))); \
  camera_refrac_model_ids_.push_back(                                  \
      static_cast<int>(CameraRefracModel::refrac_model_id));

  CAMERA_REFRAC_MODEL_CASES

#undef CAMERA_REFRAC_MODEL_CASE

  camera_refrac_params_info_ = new QLabel(tr(""), this);
  QPalette pal = QPalette(camera_refrac_params_info_->palette());
  pal.setColor(QPalette::WindowText, QColor(130, 130, 130));
  camera_refrac_params_info_->setPalette(pal);

  camera_refrac_params_text_ = new QLineEdit(this);
  camera_refrac_params_text_->setEnabled(false);

  QGroupBox* box = new QGroupBox(tr("Refractive camera model"), this);
  QVBoxLayout* vbox = new QVBoxLayout(box);

  vbox->addWidget(camera_refrac_model_cb_);
  vbox->addWidget(camera_refrac_params_info_);
  vbox->addWidget(camera_refrac_params_text_);
  vbox->addStretch(1);

  box->setLayout(vbox);

  SelectCameraRefracModel(camera_refrac_model_cb_->currentIndex());

  connect(camera_refrac_model_cb_,
          (void(QComboBox::*)(int)) & QComboBox::currentIndexChanged,
          this,
          &FeatureExtractionWidget::SelectCameraRefracModel);

  return box;
}

void FeatureExtractionWidget::showEvent(QShowEvent* event) {
  parent_->setDisabled(true);
  ReadOptions();
}

void FeatureExtractionWidget::hideEvent(QHideEvent* event) {
  parent_->setEnabled(true);
  WriteOptions();
}

void FeatureExtractionWidget::ReadOptions() {
  const CameraModelId model_id =
      CameraModelNameToId(options_->image_reader->camera_model);
  for (size_t i = 0; i < camera_model_ids_.size(); ++i) {
    if (camera_model_ids_[i] == static_cast<int>(model_id)) {
      SelectCameraModel(i);
      camera_model_cb_->setCurrentIndex(i);
      break;
    }
  }
  single_camera_cb_->setChecked(options_->image_reader->single_camera);
  single_camera_per_folder_cb_->setChecked(
      options_->image_reader->single_camera_per_folder);
  camera_params_text_->setText(
      QString::fromStdString(options_->image_reader->camera_params));

  const CameraRefracModelId refrac_model_id =
      CameraRefracModelNameToId(options_->image_reader->camera_refrac_model);
  for (size_t i = 0; i < camera_refrac_model_ids_.size(); ++i) {
    if (camera_refrac_model_ids_[i] == static_cast<int>(refrac_model_id)) {
      SelectCameraRefracModel(i);
      camera_refrac_model_cb_->setCurrentIndex(i);
      break;
    }
  }
  camera_refrac_params_text_->setText(
      QString::fromStdString(options_->image_reader->camera_refrac_params));
}

void FeatureExtractionWidget::WriteOptions() {
  options_->image_reader->camera_model =
      CameraModelIdToName(static_cast<CameraModelId>(
          camera_model_ids_[camera_model_cb_->currentIndex()]));
  options_->image_reader->single_camera = single_camera_cb_->isChecked();
  options_->image_reader->single_camera_per_folder =
      single_camera_per_folder_cb_->isChecked();
  options_->image_reader->camera_params =
      camera_params_text_->text().toUtf8().constData();

  CameraRefracModelId camera_refrac_model_id = static_cast<CameraRefracModelId>(
      camera_refrac_model_ids_[camera_refrac_model_cb_->currentIndex()]);
  if (camera_refrac_model_id != CameraRefracModelId::kInvalid) {
    options_->image_reader->camera_refrac_model =
        CameraRefracModelIdToName(camera_refrac_model_id);
    options_->image_reader->camera_refrac_params =
        camera_refrac_params_text_->text().toUtf8().constData();
  } else {
    options_->image_reader->camera_refrac_model = "NONE";
    options_->image_reader->camera_refrac_params = "";
  }
}

void FeatureExtractionWidget::SelectCameraModel(const int idx) {
  const CameraModelId model_id =
      static_cast<CameraModelId>(camera_model_ids_[idx]);
  camera_params_info_->setText(QString::fromStdString(
      StringPrintf("<small>Parameters: %s</small>",
                   CameraModelParamsInfo(model_id).c_str())));
}

void FeatureExtractionWidget::SelectCameraRefracModel(const int idx) {
  const CameraRefracModelId code =
      static_cast<CameraRefracModelId>(camera_refrac_model_ids_[idx]);
  if (code != CameraRefracModelId::kInvalid) {
    camera_refrac_params_info_->setText(QString::fromStdString(
        StringPrintf("<small>Parameters: %s</small>",
                     CameraRefracModelParamsInfo(code).c_str())));
    camera_refrac_params_text_->setEnabled(true);
  } else {
    camera_refrac_params_info_->setText(QString::fromStdString(StringPrintf(
        "<small>No parameters, use non-refractive camera model</small>")));
    camera_refrac_params_text_->setEnabled(false);
  }
}

void FeatureExtractionWidget::Extract() {
  // If the custom parameter radiobuttion is not checked, but the
  // parameters textbox contains parameters.
  const auto old_camera_params_text = camera_params_text_->text();
  if (!camera_params_custom_rb_->isChecked()) {
    camera_params_text_->setText("");
  }

  // If the refractove model is selected as NONE, but the
  // parameters textbox contains parameters.
  const auto old_camera_refrac_params_text = camera_refrac_params_text_->text();
  if (camera_refrac_model_ids_[camera_refrac_model_cb_->currentIndex()] == -1) {
    camera_refrac_params_text_->setText("");
  }

  WriteOptions();

  if (!ExistsCameraModelWithName(options_->image_reader->camera_model)) {
    QMessageBox::critical(this, "", tr("Camera model does not exist"));
    return;
  }

  const std::vector<double> camera_params =
      CSVToVector<double>(options_->image_reader->camera_params);
  const auto camera_code =
      CameraModelNameToId(options_->image_reader->camera_model);

  if (camera_params_custom_rb_->isChecked() &&
      !CameraModelVerifyParams(camera_code, camera_params)) {
    QMessageBox::critical(this, "", tr("Invalid camera parameters"));
    return;
  }

  const auto camera_refrac_model_code =
      options_->image_reader->camera_refrac_model;
  if (camera_refrac_model_code != "NONE") {
    if (!ExistsCameraRefracModelWithName(camera_refrac_model_code)) {
      QMessageBox::critical(
          this, "", tr("Refractive camera model does not exist"));
      return;
    }

    const std::vector<double> camera_refrac_params =
        CSVToVector<double>(options_->image_reader->camera_refrac_params);
    const CameraRefracModelId camera_refrac_model_id =
        CameraRefracModelNameToId(camera_refrac_model_code);
    if (!CameraRefracModelVerifyParams(camera_refrac_model_id,
                                       camera_refrac_params)) {
      QMessageBox::critical(
          this, "", tr("Invalid refractive camera model parameters"));
      return;
    }
  }

  QWidget* widget =
      static_cast<QScrollArea*>(tab_widget_->currentWidget())->widget();
  static_cast<ExtractionWidget*>(widget)->Run();

  camera_params_text_->setText(old_camera_params_text);
  camera_refrac_params_text_->setText(old_camera_refrac_params_text);
}

}  // namespace colmap